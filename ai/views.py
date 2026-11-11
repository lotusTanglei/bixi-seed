import json
import logging
import re
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from features.models import Feature, FeatureRecord
from features.services import feature_action_enabled, feature_permission_code, validate_manifest, validate_record_data
from features.views import scoped_records, serialize_record
from organizations.services import get_active_membership, get_membership_permissions, membership_data_scope, user_has_permission, write_audit

from .models import Conversation, FeatureProposal, LLMProviderConfig, Message, ToolCallProposal
from .providers import ProviderConfigurationError, get_provider, parse_json_response


logger = logging.getLogger(__name__)
FEATURE_KEY_RE = re.compile(r"^[a-z][a-z0-9-]{1,99}$")


def _config_payload(config):
    return {
        "provider": config.provider,
        "base_url": config.base_url,
        "model": config.model,
        "is_enabled": config.is_enabled,
        "has_api_key": bool(config.api_key_encrypted),
        "updated_at": config.updated_at,
    }


def _conversation_payload(conversation):
    return {
        "id": conversation.id,
        "title": conversation.title or "新对话",
        "updated_at": conversation.updated_at,
    }


def _proposal_payload(proposal):
    return {
        "id": proposal.id,
        "requirement": proposal.requirement,
        "key": proposal.key,
        "name": proposal.name,
        "description": proposal.description,
        "manifest": proposal.manifest,
        "status": proposal.status,
        "feature_id": str(proposal.feature_id) if proposal.feature_id else None,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
    }


TOOL_CATALOG = {
    "feature.record.create": {
        "risk": "medium",
        "permission": "create",
        "description": "创建一条已发布 Feature 数据",
        "arguments": {"type": "object", "required": ["feature_id", "data"], "additionalProperties": False,
                      "properties": {"feature_id": {"type": "string", "format": "uuid"}, "data": {"type": "object"}}},
    },
    "feature.record.update": {
        "risk": "high",
        "permission": "update",
        "description": "修改一条已发布 Feature 数据",
        "arguments": {"type": "object", "required": ["feature_id", "record_id", "data"], "additionalProperties": False,
                      "properties": {"feature_id": {"type": "string", "format": "uuid"}, "record_id": {"type": "integer", "minimum": 1}, "data": {"type": "object"}}},
    },
    "feature.record.delete": {
        "risk": "high",
        "permission": "delete",
        "description": "删除一条已发布 Feature 数据",
        "arguments": {"type": "object", "required": ["feature_id", "record_id"], "additionalProperties": False,
                      "properties": {"feature_id": {"type": "string", "format": "uuid"}, "record_id": {"type": "integer", "minimum": 1}}},
    },
}
MODEL_TOOL_NAMES = {
    "feature_record_create": "feature.record.create",
    "feature_record_update": "feature.record.update",
    "feature_record_delete": "feature.record.delete",
}


def _tool_payload(item):
    return {
        "id": item.id,
        "tool": item.tool,
        "risk": item.risk,
        "arguments": item.arguments,
        "preview": item.preview,
        "diff": item.diff,
        "result": {key: value for key, value in item.result.items() if key != "undo"},
        "status": item.status,
        "error_message": item.error_message,
        "can_revoke": item.status == "proposed" or (item.status == "confirmed" and bool(item.result.get("undo"))),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _revoked_tool_payload(request, proposal):
    visible, _ = ToolCallProposalDetailView()._get(request, proposal.pk)
    if visible is not None:
        return _tool_payload(proposal)
    return {"id": proposal.pk, "tool": proposal.tool, "risk": proposal.risk, "status": proposal.status,
            "preview": {}, "diff": {"fields": {}, "permissions": {}, "data": {}}, "result": {},
            "error_message": "", "can_revoke": False}


class LLMConfigView(APIView):
    def get(self, request):
        if not user_has_permission(request, "ai.configure"):
            return Response({"detail": "没有配置 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        config, _ = LLMProviderConfig.objects.get_or_create(organization=membership.organization)
        return Response(_config_payload(config))

    def patch(self, request):
        if not user_has_permission(request, "ai.configure"):
            return Response({"detail": "没有配置 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        config, _ = LLMProviderConfig.objects.get_or_create(organization=membership.organization)
        if "provider" in request.data and request.data["provider"] != "openai-compatible":
            return Response({"detail": "当前版本只支持 openai-compatible Provider"}, status=status.HTTP_400_BAD_REQUEST)
        if "model" in request.data and not str(request.data["model"]).strip():
            return Response({"detail": "模型名称不能为空"}, status=status.HTTP_400_BAD_REQUEST)
        for field in ("provider", "base_url", "model"):
            if field in request.data:
                setattr(config, field, str(request.data[field]).strip())
        if "is_enabled" in request.data:
            config.is_enabled = request.data["is_enabled"] in (True, 1, "1", "true", "True")
        if "api_key" in request.data and request.data["api_key"]:
            config.set_api_key(str(request.data["api_key"]))
        config.save()
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="ai.configured",
            object_type="llm_config",
            object_id=config.pk,
            metadata={"provider": config.provider, "model": config.model, "has_api_key": bool(config.api_key_encrypted)},
        )
        return Response(_config_payload(config))


class ConversationListView(APIView):
    def get(self, request):
        if not user_has_permission(request, "ai.use"):
            return Response({"detail": "没有使用 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        conversations = Conversation.objects.filter(organization=membership.organization, user=request.user)
        return Response([_conversation_payload(item) for item in conversations])

    def post(self, request):
        if not user_has_permission(request, "ai.use"):
            return Response({"detail": "没有使用 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        conversation = Conversation.objects.create(
            organization=membership.organization,
            user=request.user,
            title=str(request.data.get("title", "")).strip()[:200],
        )
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="ai.conversation.created",
            object_type="conversation",
            object_id=conversation.pk,
            metadata={},
        )
        return Response(_conversation_payload(conversation), status=201)


class ConversationMessagesView(APIView):
    def get(self, request, conversation_id):
        if not user_has_permission(request, "ai.use"):
            return Response({"detail": "没有使用 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        conversation = get_object_or_404(
            Conversation,
            id=conversation_id,
            organization=membership.organization,
            user=request.user,
        )
        return Response(list(conversation.messages.values("id", "role", "content", "created_at")))


def _event(event, payload):
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


class ChatView(APIView):
    def post(self, request):
        if not user_has_permission(request, "ai.use"):
            return Response({"detail": "没有使用 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        content = str(request.data.get("content", "")).strip()
        if not content or len(content) > 12000:
            return Response({"detail": "消息不能为空且不能超过 12000 个字符"}, status=status.HTTP_400_BAD_REQUEST)
        membership = get_active_membership(request)
        conversation_id = request.data.get("conversation_id")
        if conversation_id:
            conversation = get_object_or_404(
                Conversation,
                id=conversation_id,
                organization=membership.organization,
                user=request.user,
            )
        else:
            conversation = Conversation.objects.create(
                organization=membership.organization,
                user=request.user,
                title=content[:40],
            )
            write_audit(
                organization=membership.organization,
                actor=request.user,
                action="ai.conversation.created",
                object_type="conversation",
                object_id=conversation.pk,
                metadata={},
            )
        try:
            provider = get_provider(membership.organization)
        except ProviderConfigurationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        Message.objects.create(conversation=conversation, role="user", content=content)
        messages = list(conversation.messages.order_by("created_at").values("role", "content"))

        def stream():
            assistant_parts = []
            try:
                completion = provider.stream(messages)
                for chunk in completion:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        assistant_parts.append(delta)
                        yield _event("token", {"content": delta})
                assistant = Message.objects.create(
                    conversation=conversation,
                    role="assistant",
                    content="".join(assistant_parts),
                )
                write_audit(
                    organization=conversation.organization,
                    actor=request.user,
                    action="ai.conversation.completed",
                    object_type="conversation",
                    object_id=conversation.pk,
                    metadata={"message_id": assistant.pk},
                )
                yield _event("done", {"message_id": assistant.id})
            except Exception:
                logger.exception("AI completion failed")
                write_audit(
                    organization=conversation.organization,
                    actor=request.user,
                    action="ai.conversation.completed",
                    object_type="conversation",
                    object_id=conversation.pk,
                    metadata={},
                    success=False,
                )
                yield _event("error", {"message": "AI 服务调用失败，请检查模型配置"})

        response = StreamingHttpResponse(stream(), content_type="text/event-stream; charset=utf-8")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class FeaturePlanView(APIView):
    def post(self, request):
        if not user_has_permission(request, "ai.use"):
            return Response({"detail": "没有使用 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        requirement = str(request.data.get("requirement", "")).strip()
        if not requirement or len(requirement) > 8000:
            return Response({"detail": "需求不能为空且不能超过 8000 个字符"}, status=status.HTTP_400_BAD_REQUEST)
        membership = get_active_membership(request)
        try:
            provider = get_provider(membership.organization)
            content = provider.complete_json(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是 Bixi Seed 的业务功能规划助手。只输出一个 JSON 对象，不要 Markdown，不要代码。"
                            "JSON 必须包含 key、name、description、manifest。key 使用小写英文和连字符，"
                            "manifest.version 必须为 1，fields 只能使用 text、number、date、enum、boolean；"
                            "每个字段包含 key、label、type、required，可选 options、max_length、min、max；"
                            "可以包含 list、form、detail、actions、permissions。不要生成 SQL、Python、Shell、文件路径或任意函数。"
                        ),
                    },
                    {"role": "user", "content": requirement},
                ]
            )
            proposal_data = parse_json_response(content)
        except (ProviderConfigurationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except Exception:
            logger.exception("AI feature planning failed")
            return Response({"detail": "AI 方案生成失败，请检查模型配置"}, status=status.HTTP_502_BAD_GATEWAY)
        if not isinstance(proposal_data, dict):
            return Response({"detail": "AI 返回的方案格式不正确"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        key = str(proposal_data.get("key", "")).strip()
        name = str(proposal_data.get("name", "")).strip()
        description = str(proposal_data.get("description", "")).strip()[:500]
        manifest = proposal_data.get("manifest", {})
        errors = validate_manifest(manifest)
        if not FEATURE_KEY_RE.fullmatch(key):
            errors.append("key 必须是 2 到 100 个字符的小写英文、数字和连字符")
        if not name:
            errors.append("name 不能为空")
        if errors:
            return Response({"detail": errors}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        proposal = FeatureProposal.objects.create(
            organization=membership.organization,
            user=request.user,
            requirement=requirement,
            key=key,
            name=name,
            description=description,
            manifest=manifest,
        )
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="feature.proposed",
            object_type="feature_proposal",
            object_id=proposal.pk,
            metadata={"key": key},
        )
        return Response(_proposal_payload(proposal), status=status.HTTP_201_CREATED)


class FeatureProposalConfirmView(APIView):
    @transaction.atomic
    def post(self, request, proposal_id):
        if not user_has_permission(request, "feature.manage"):
            return Response({"detail": "没有管理功能的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        proposal = get_object_or_404(FeatureProposal, id=proposal_id, organization=membership.organization)
        if proposal.status != "proposed":
            return Response({"detail": "该方案已经处理"}, status=status.HTTP_400_BAD_REQUEST)
        key = str(request.data.get("key", proposal.key)).strip()
        name = str(request.data.get("name", proposal.name)).strip()
        description = str(request.data.get("description", proposal.description)).strip()[:500]
        manifest = request.data.get("manifest", proposal.manifest)
        errors = validate_manifest(manifest)
        if not FEATURE_KEY_RE.fullmatch(key):
            errors.append("key 格式不正确")
        if not name:
            errors.append("name 不能为空")
        if Feature.objects.filter(organization=membership.organization, key=key).exists():
            errors.append("功能编码已存在")
        if errors:
            return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)
        feature = Feature.objects.create(
            organization=membership.organization,
            key=key,
            name=name,
            description=description,
            manifest=manifest,
            created_by=request.user,
        )
        proposal.key = key
        proposal.name = name
        proposal.description = description
        proposal.manifest = manifest
        proposal.status = "created"
        proposal.feature = feature
        proposal.save(update_fields=["key", "name", "description", "manifest", "status", "feature", "updated_at"])
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="feature.proposal.confirmed",
            object_type="feature",
            object_id=feature.pk,
            metadata={"proposal_id": proposal.pk, "status": feature.status},
        )
        from features.views import serialize_feature

        return Response({"proposal": _proposal_payload(proposal), "feature": serialize_feature(feature)}, status=201)


class FeatureProposalRejectView(APIView):
    def post(self, request, proposal_id):
        if not user_has_permission(request, "feature.manage"):
            return Response({"detail": "没有管理功能的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        proposal = get_object_or_404(FeatureProposal, id=proposal_id, organization=membership.organization)
        if proposal.status != "proposed":
            return Response({"detail": "该方案已经处理"}, status=status.HTTP_400_BAD_REQUEST)
        proposal.status = "rejected"
        proposal.save(update_fields=["status", "updated_at"])
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="feature.proposal.rejected",
            object_type="feature_proposal",
            object_id=proposal.pk,
            metadata={},
        )
        return Response(_proposal_payload(proposal))


class ToolCatalogView(APIView):
    def get(self, request):
        if not user_has_permission(request, "ai.use"):
            return Response({"detail": "没有使用 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        return Response(
            [
                {"name": name, "risk": spec["risk"], "description": spec["description"], "arguments": spec["arguments"]}
                for name, spec in TOOL_CATALOG.items()
            ]
        )


def _tool_arguments_error(tool, arguments):
    if not isinstance(arguments, dict):
        return "arguments 必须是对象"
    spec = TOOL_CATALOG[tool]["arguments"]
    if set(arguments) - set(spec["properties"]) or set(spec["required"]) - set(arguments):
        return "工具参数缺失或包含未开放字段"
    try:
        if not isinstance(arguments["feature_id"], str):
            raise ValueError
        uuid.UUID(arguments["feature_id"])
    except (ValueError, TypeError, AttributeError):
        return "feature_id 必须是 UUID 字符串"
    if "record_id" in arguments and (
        not isinstance(arguments["record_id"], int) or isinstance(arguments["record_id"], bool) or arguments["record_id"] < 1
    ):
        return "record_id 必须是正整数"
    if "data" in arguments and not isinstance(arguments["data"], dict):
        return "data 必须是对象"
    return None


def _tool_audit(request, action, *, proposal=None, tool="", success=True, reason=""):
    membership = get_active_membership(request)
    write_audit(
        organization=membership.organization if membership else None,
        actor=request.user,
        action=action,
        object_type="tool_call_proposal",
        object_id=proposal.pk if proposal else "",
        metadata={"tool": proposal.tool if proposal else tool, "risk": proposal.risk if proposal else TOOL_CATALOG.get(tool, {}).get("risk", ""), "reason": reason},
        success=success,
    )


def _tool_error(request, detail, *, proposal=None, tool="", code=400, action="ai.tool.rejected"):
    _tool_audit(request, action, proposal=proposal, tool=tool, success=False, reason=str(detail)[:200])
    return Response({"detail": detail}, status=code)


def _tool_context(request, tool, arguments, *, lock=False):
    error = _tool_arguments_error(tool, arguments)
    if error:
        return None, None, None, None, error
    membership = get_active_membership(request)
    if membership is None or not user_has_permission(request, "ai.use"):
        return None, None, None, None, "当前组织成员或 AI 权限已失效"
    features = Feature.objects.select_for_update() if lock else Feature.objects
    try:
        feature = features.get(organization=membership.organization, id=arguments["feature_id"], status="published")
    except (Feature.DoesNotExist, ValidationError, ValueError, TypeError):
        return None, None, None, None, "已发布功能不存在"
    if validate_manifest(feature.manifest):
        return None, None, None, None, "功能定义不可用"
    action = TOOL_CATALOG[tool]["permission"]
    if not feature_action_enabled(feature, action):
        return None, None, None, None, "该功能未开放此操作"
    if not user_has_permission(request, feature_permission_code(feature, action)):
        return None, None, None, None, "没有执行该功能操作的权限"
    context = {
        "fields": feature.manifest["fields"],
        "permissions": {
            "required": feature_permission_code(feature, action),
            "granted": sorted(get_membership_permissions(membership)),
            "data_scope": membership_data_scope(membership),
        },
        "manifest": feature.manifest,
    }
    preview = {"operation": action, "feature_id": str(feature.pk), "context": context}
    if tool == "feature.record.create":
        data = arguments["data"]
        errors = validate_record_data(feature.manifest, data)
        if errors:
            return None, None, None, None, errors
        preview["after"] = data
        data_diff = {"added": data, "changed": {}, "removed": {}}
        record = None
    else:
        records = FeatureRecord.objects.select_for_update() if lock else FeatureRecord.objects.all()
        record = scoped_records(records, membership).filter(feature=feature, id=arguments["record_id"]).first()
        if record is None:
            return None, None, None, None, "数据记录不存在或超出数据范围"
        before = serialize_record(record, feature)["data"]
        preview.update({"record_id": record.pk, "record_revision": record.updated_at.isoformat(), "before": before})
        if tool == "feature.record.delete":
            data_diff = {"added": {}, "changed": {}, "removed": before}
        else:
            after = dict(record.data)
            after.update(arguments["data"])
            errors = validate_record_data(feature.manifest, after)
            if errors:
                return None, None, None, None, errors
            preview["after"] = after
            data_diff = {
                "added": {key: value for key, value in after.items() if key not in before},
                "changed": {key: {"before": before[key], "after": after[key]} for key in after if key in before and before[key] != after[key]},
                "removed": {key: value for key, value in before.items() if key not in after},
            }
    # These record tools do not alter the Feature schema or permission definitions.
    diff = {**data_diff, "data": data_diff, "fields": {"before": context["fields"], "after": context["fields"]},
            "permissions": {"before": context["permissions"], "after": context["permissions"]}}
    return feature, record, preview, diff, None


def _record_snapshot(record):
    if record is None:
        return None
    return {"id": record.pk, "data": record.data, "created_by_id": record.created_by_id,
            "updated_by_id": record.updated_by_id, "created_at": record.created_at.isoformat(), "updated_at": record.updated_at.isoformat()}


def _execute_tool(request, proposal, feature, record, preview):
    before = _record_snapshot(record)
    if proposal.tool == "feature.record.create":
        record = FeatureRecord.objects.create(feature=feature, data=proposal.arguments["data"], created_by=request.user, updated_by=request.user)
        result = {"id": str(record.pk), "data": record.data}
        action = "feature.record.created"
    elif proposal.tool == "feature.record.update":
        record.data = preview["after"]
        record.updated_by = request.user
        record.save(update_fields=["data", "updated_by", "updated_at"])
        result = {"id": str(record.pk), "data": record.data}
        action = "feature.record.updated"
    else:
        record_id = record.pk
        record.delete()
        record = None
        result = {"deleted": True, "record_id": record_id}
        action = "feature.record.deleted"
    result["undo"] = {"feature_id": str(feature.pk), "before": before, "after": _record_snapshot(record)}
    write_audit(organization=feature.organization, actor=request.user, action=action, object_type="feature_record",
                object_id=result.get("id", result.get("record_id", "")), metadata={"feature": feature.key, "via_tool": proposal.tool})
    return result


class ToolCallProposalListView(APIView):
    @transaction.atomic
    def post(self, request):
        tool = str(request.data.get("tool", "")).strip()
        if not user_has_permission(request, "ai.use"):
            return _tool_error(request, "没有使用 AI 的权限", tool=tool, code=403)
        if tool not in TOOL_CATALOG:
            return _tool_error(request, "工具不存在或未开放", tool=tool)
        arguments = request.data.get("arguments", {})
        feature, record, preview, diff, error = _tool_context(request, tool, arguments)
        if error:
            return _tool_error(request, error, tool=tool)
        proposal = ToolCallProposal.objects.create(
            organization=get_active_membership(request).organization, user=request.user, tool=tool,
            risk=TOOL_CATALOG[tool]["risk"], arguments=arguments, preview=preview, diff=diff,
        )
        _tool_audit(request, "ai.tool.proposed", proposal=proposal)
        return Response(_tool_payload(proposal), status=status.HTTP_201_CREATED)


class ToolCallPlanView(APIView):
    def post(self, request):
        if not user_has_permission(request, "ai.use"):
            return _tool_error(request, "没有使用 AI 的权限", code=403)
        requirement = request.data.get("requirement", "")
        if not isinstance(requirement, str) or not requirement.strip() or len(requirement) > 8000:
            return _tool_error(request, "需求不能为空且不能超过 8000 个字符")
        feature_id = request.data.get("feature_id")
        try:
            selected_id = uuid.UUID(feature_id) if isinstance(feature_id, str) else None
        except (ValueError, TypeError, AttributeError):
            selected_id = None
        if selected_id is None:
            return _tool_error(request, "feature_id 必须是 UUID 字符串")
        membership = get_active_membership(request)
        feature = Feature.objects.filter(organization=membership.organization, pk=selected_id, status="published").first()
        if feature is None or validate_manifest(feature.manifest):
            return _tool_error(request, "已发布功能不存在", code=404)
        allowed = {
            alias: tool for alias, tool in MODEL_TOOL_NAMES.items()
            if feature_action_enabled(feature, TOOL_CATALOG[tool]["permission"])
            and user_has_permission(request, feature_permission_code(feature, TOOL_CATALOG[tool]["permission"]))
        }
        if not allowed:
            return _tool_error(request, "没有可规划的功能操作权限", code=403)
        tools = [
            {"type": "function", "function": {"name": alias, "description": TOOL_CATALOG[tool]["description"],
             "parameters": TOOL_CATALOG[tool]["arguments"]}}
            for alias, tool in allowed.items()
        ]
        try:
            provider = get_provider(membership.organization)
            planned = provider.complete_tool_call([
                {"role": "system", "content": "仅为用户选定的功能生成一个记录工具方案。feature_id 必须保持一致；"
                 "只生成待确认提案，不执行操作。没有查询记录的工具，不要猜测记录编号或字段值。功能上下文："
                 + json.dumps({"feature_id": str(feature.pk), "name": feature.name, "fields": feature.manifest["fields"]}, ensure_ascii=False)},
                {"role": "user", "content": requirement.strip()},
            ], tools)
        except ProviderConfigurationError:
            return _tool_error(request, "请先配置当前组织可用的 AI 模型和 API Key", code=422, action="ai.tool.plan_failed")
        except ValueError:
            return _tool_error(request, "AI 必须返回一个有效的固定工具方案", code=422, action="ai.tool.plan_failed")
        except Exception:
            logger.exception("Controlled tool planning failed")
            return _tool_error(request, "AI 工具规划失败，请检查模型配置", code=502, action="ai.tool.plan_failed")
        current = get_active_membership(request)
        if current is None or current.organization_id != membership.organization_id or not user_has_permission(request, "ai.use"):
            return _tool_error(request, "当前组织成员或 AI 权限已失效", code=403, action="ai.tool.plan_failed")
        if not isinstance(planned, dict) or planned.get("name") not in allowed:
            return _tool_error(request, "AI 返回了未开放的工具", code=422, action="ai.tool.plan_failed")
        tool = allowed[planned["name"]]
        arguments = planned.get("arguments")
        error = _tool_arguments_error(tool, arguments)
        if error:
            return _tool_error(request, error, tool=tool, code=422, action="ai.tool.plan_failed")
        if uuid.UUID(arguments["feature_id"]) != selected_id:
            return _tool_error(request, "AI 工具方案不能切换用户选定的功能", tool=tool, code=422, action="ai.tool.plan_failed")
        feature, record, preview, diff, error = _tool_context(request, tool, arguments)
        if error:
            return _tool_error(request, error, tool=tool, code=422, action="ai.tool.plan_failed")
        with transaction.atomic():
            proposal = ToolCallProposal.objects.create(
                organization=membership.organization, user=request.user, tool=tool,
                risk=TOOL_CATALOG[tool]["risk"], arguments=arguments, preview=preview, diff=diff,
            )
            _tool_audit(request, "ai.tool.planned", proposal=proposal)
            _tool_audit(request, "ai.tool.proposed", proposal=proposal)
        return Response(_tool_payload(proposal), status=201)


class ToolCallProposalDetailView(APIView):
    def _get(self, request, proposal_id):
        if not user_has_permission(request, "ai.use"):
            return None, Response({"detail": "没有使用 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        query = ToolCallProposal.objects.filter(organization=membership.organization, id=proposal_id)
        if not (user_has_permission(request, "feature.manage") and membership_data_scope(membership)["mode"] == "all"):
            query = query.filter(user=request.user)
        proposal = query.first()
        if proposal is None:
            return None, None
        feature = Feature.objects.filter(organization=membership.organization, id=proposal.arguments.get("feature_id"), status="published").first()
        action = TOOL_CATALOG[proposal.tool]["permission"]
        if (feature is None or validate_manifest(feature.manifest) or not feature_action_enabled(feature, action)
                or not user_has_permission(request, feature_permission_code(feature, action))
                or feature.manifest != proposal.preview.get("context", {}).get("manifest")):
            return None, None
        if membership_data_scope(membership)["mode"] == "own":
            undo = proposal.result.get("undo", {})
            snapshot = undo.get("before") or undo.get("after")
            if snapshot:
                if snapshot["created_by_id"] != request.user.pk:
                    return None, None
            elif proposal.tool != "feature.record.create" and not scoped_records(FeatureRecord.objects.all(), membership).filter(
                feature=feature, pk=proposal.arguments["record_id"]
            ).exists():
                return None, None
        return proposal, None

    def get(self, request, proposal_id):
        proposal, error = self._get(request, proposal_id)
        if error:
            return error
        if proposal is None:
            return Response({"detail": "方案不存在"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_tool_payload(proposal))


class ToolCallProposalConfirmView(APIView):
    @transaction.atomic
    def post(self, request, proposal_id):
        if not user_has_permission(request, "ai.use"):
            return _tool_error(request, "没有使用 AI 的权限", code=403)
        proposal = ToolCallProposal.objects.select_for_update().filter(
            organization=get_active_membership(request).organization, id=proposal_id, user=request.user
        ).first()
        if proposal is None:
            return _tool_error(request, "方案不存在", code=404)
        if request.data.get("confirm") is not True:
            return _tool_error(request, "请确认工具执行", proposal=proposal)
        if proposal.status != "proposed":
            return _tool_error(request, "该工具方案已经处理", proposal=proposal)
        feature, record, preview, diff, error = _tool_context(request, proposal.tool, proposal.arguments, lock=True)
        if not error and (preview != proposal.preview or diff != proposal.diff):
            error = "方案预览已过期，请重新生成并确认"
        if error:
            proposal.status = "failed"
            proposal.error_message = str(error)[:500]
            proposal.save(update_fields=["status", "error_message", "updated_at"])
            return _tool_error(request, error, proposal=proposal, code=409, action="ai.tool.failed")
        try:
            with transaction.atomic():
                result = _execute_tool(request, proposal, feature, record, preview)
                proposal.result = result
                proposal.status = "confirmed"
                proposal.save(update_fields=["result", "status", "updated_at"])
                _tool_audit(request, "ai.tool.confirmed", proposal=proposal)
        except Exception:
            logger.exception("Controlled tool execution failed")
            proposal.status = "failed"
            proposal.error_message = "工具执行失败，变更已回滚"
            proposal.save(update_fields=["status", "error_message", "updated_at"])
            return _tool_error(request, proposal.error_message, proposal=proposal, code=500, action="ai.tool.failed")
        return Response(_tool_payload(proposal))


def _undo_tool(request, proposal):
    membership = get_active_membership(request)
    if membership is None or not user_has_permission(request, "ai.use"):
        return "当前组织成员或 AI 权限已失效"
    undo = proposal.result.get("undo")
    if not isinstance(undo, dict):
        return "该历史方案没有可撤销快照"
    feature = Feature.objects.select_for_update().filter(organization=membership.organization, id=undo["feature_id"], status="published").first()
    if feature is None or validate_manifest(feature.manifest):
        return "原功能不可用，不能撤销"
    action = {"feature.record.create": "delete", "feature.record.update": "update", "feature.record.delete": "create"}[proposal.tool]
    if not feature_action_enabled(feature, action) or not user_has_permission(request, feature_permission_code(feature, action)):
        return "没有撤销该变更所需的当前权限"
    if feature.manifest != proposal.preview.get("context", {}).get("manifest"):
        return "功能字段或权限定义已变化，不能撤销"
    before, after = undo.get("before"), undo.get("after")
    record_id = (after or before)["id"]
    record = FeatureRecord.objects.select_for_update().filter(pk=record_id).first()
    if after:
        if record is None or record.feature_id != feature.pk or _record_snapshot(record) != after:
            return "数据在执行后已变化，不能覆盖撤销"
        if not scoped_records(FeatureRecord.objects.filter(pk=record_id), membership).exists():
            return "原数据已超出当前数据范围"
    else:
        if record is not None:
            return "原记录编号已被占用，不能覆盖撤销"
        if membership_data_scope(membership)["mode"] == "own" and before["created_by_id"] != request.user.pk:
            return "原数据已超出当前数据范围"
    if before and validate_record_data(feature.manifest, before["data"]):
        return "原数据不满足当前字段规则，不能撤销"
    if before is None:
        record.delete()
    elif after is None:
        restored = FeatureRecord.objects.create(pk=record_id, feature=feature, data=before["data"],
            created_by_id=before["created_by_id"], updated_by=request.user)
        FeatureRecord.objects.filter(pk=restored.pk).update(created_at=before["created_at"])
    else:
        record.data = before["data"]
        record.updated_by = request.user
        record.save(update_fields=["data", "updated_by", "updated_at"])
    write_audit(organization=membership.organization, actor=request.user, action="feature.record.reverted", object_type="feature_record",
                object_id=record_id, metadata={"proposal_id": proposal.pk, "tool": proposal.tool})
    return None


class ToolCallProposalRevokeView(APIView):
    @transaction.atomic
    def post(self, request, proposal_id):
        if not user_has_permission(request, "ai.use"):
            return _tool_error(request, "没有使用 AI 的权限", code=403)
        proposal = ToolCallProposal.objects.select_for_update().filter(
            organization=get_active_membership(request).organization, id=proposal_id, user=request.user
        ).first()
        if proposal is None:
            return _tool_error(request, "方案不存在", code=404)
        if request.data.get("confirm") is not True:
            return _tool_error(request, "请确认撤销", proposal=proposal)
        if proposal.status not in {"proposed", "confirmed"}:
            return _tool_error(request, "该工具方案已经处理", proposal=proposal)
        was_confirmed = proposal.status == "confirmed"
        try:
            with transaction.atomic():
                if was_confirmed:
                    error = _undo_tool(request, proposal)
                    if error:
                        return _tool_error(request, error, proposal=proposal, code=409, action="ai.tool.revert_failed")
                proposal.status = "revoked"
                proposal.save(update_fields=["status", "updated_at"])
                _tool_audit(request, "ai.tool.reverted" if was_confirmed else "ai.tool.revoked", proposal=proposal)
        except Exception:
            logger.exception("Controlled tool revert failed")
            return _tool_error(request, "撤销失败，变更已回滚", proposal=proposal, code=500, action="ai.tool.revert_failed")
        return Response(_revoked_tool_payload(request, proposal))
