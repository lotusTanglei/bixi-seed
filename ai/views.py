import json
import logging
import re

from django.db import transaction
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from features.models import Feature, FeatureRecord
from features.services import feature_permission_code, validate_manifest, validate_record_data
from features.views import scoped_records, serialize_record
from organizations.services import get_active_membership, user_has_permission, write_audit

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
        "arguments": {"type": "object", "required": ["feature_id", "data"]},
    },
    "feature.record.update": {
        "risk": "high",
        "permission": "update",
        "description": "修改一条已发布 Feature 数据",
        "arguments": {"type": "object", "required": ["feature_id", "record_id", "data"]},
    },
    "feature.record.delete": {
        "risk": "high",
        "permission": "delete",
        "description": "删除一条已发布 Feature 数据",
        "arguments": {"type": "object", "required": ["feature_id", "record_id"]},
    },
}


def _tool_payload(item):
    return {
        "id": item.id,
        "tool": item.tool,
        "risk": item.risk,
        "arguments": item.arguments,
        "preview": item.preview,
        "diff": item.diff,
        "result": item.result,
        "status": item.status,
        "error_message": item.error_message,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


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


def _tool_context(request, tool, arguments):
    if not isinstance(arguments, dict):
        return None, None, None, None, "arguments 必须是对象"
    try:
        feature = Feature.objects.get(
            organization=get_active_membership(request).organization,
            id=arguments.get("feature_id"),
            status="published",
        )
    except (Feature.DoesNotExist, ValueError, TypeError):
        return None, None, None, None, "已发布功能不存在"
    errors = validate_manifest(feature.manifest)
    if errors:
        return None, None, None, None, "功能定义不可用"
    action = TOOL_CATALOG[tool]["permission"]
    if not user_has_permission(request, feature_permission_code(feature, action)):
        return None, None, None, None, "没有执行该功能操作的权限"
    if tool == "feature.record.create":
        data = arguments.get("data")
        errors = validate_record_data(feature.manifest, data)
        if errors:
            return None, None, None, None, errors
        preview = {"operation": "create", "feature_id": str(feature.pk), "after": data}
        diff = {"added": data, "changed": {}, "removed": {}}
        return feature, None, preview, diff, None
    membership = get_active_membership(request)
    try:
        record = scoped_records(FeatureRecord.objects.all(), membership).filter(
            feature=feature, id=arguments.get("record_id")
        ).first()
    except (TypeError, ValueError):
        return None, None, None, None, "数据记录编号无效"
    if record is None:
        return None, None, None, None, "数据记录不存在或超出数据范围"
    if tool == "feature.record.delete":
        before = serialize_record(record, feature)["data"]
        return (
            feature,
            record,
            {"operation": "delete", "feature_id": str(feature.pk), "record_id": record.pk, "before": before},
            {"added": {}, "changed": {}, "removed": before},
            None,
        )
    patch_data = arguments.get("data")
    if not isinstance(patch_data, dict):
        return None, None, None, None, "data 必须是对象"
    after = dict(record.data)
    after.update(patch_data)
    errors = validate_record_data(feature.manifest, after)
    if errors:
        return None, None, None, None, errors
    before = serialize_record(record, feature)["data"]
    changed = {key: {"before": before.get(key), "after": after.get(key)} for key in after if before.get(key) != after.get(key)}
    return (
        feature,
        record,
        {"operation": "update", "feature_id": str(feature.pk), "record_id": record.pk, "before": before, "after": after},
        {"added": {}, "changed": changed, "removed": {}},
        None,
    )


class ToolCallProposalListView(APIView):
    def post(self, request):
        if not user_has_permission(request, "ai.use"):
            return Response({"detail": "没有使用 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        tool = str(request.data.get("tool", "")).strip()
        if tool not in TOOL_CATALOG:
            return Response({"detail": "工具不存在或未开放"}, status=status.HTTP_400_BAD_REQUEST)
        arguments = request.data.get("arguments", {})
        membership = get_active_membership(request)
        feature, record, preview, diff, error = _tool_context(request, tool, arguments)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        proposal = ToolCallProposal.objects.create(
            organization=membership.organization,
            user=request.user,
            tool=tool,
            risk=TOOL_CATALOG[tool]["risk"],
            arguments=arguments,
            preview=preview,
            diff=diff,
        )
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="ai.tool.proposed",
            object_type="tool_call_proposal",
            object_id=proposal.pk,
            metadata={"tool": tool, "risk": proposal.risk},
        )
        return Response(_tool_payload(proposal), status=status.HTTP_201_CREATED)


class ToolCallProposalDetailView(APIView):
    def _get(self, request, proposal_id):
        if not user_has_permission(request, "ai.use"):
            return None, Response({"detail": "没有使用 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        query = ToolCallProposal.objects.filter(organization=membership.organization, id=proposal_id)
        if not user_has_permission(request, "feature.manage"):
            query = query.filter(user=request.user)
        return query.first(), None

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
        if request.data.get("confirm") is not True:
            return Response({"detail": "请确认工具执行"}, status=status.HTTP_400_BAD_REQUEST)
        if not user_has_permission(request, "ai.use"):
            return Response({"detail": "没有使用 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        proposal = ToolCallProposal.objects.select_for_update().filter(
            organization=membership.organization, id=proposal_id, user=request.user
        ).first()
        if proposal is None:
            return Response({"detail": "方案不存在"}, status=status.HTTP_404_NOT_FOUND)
        if proposal.status != "proposed":
            return Response({"detail": "该工具方案已经处理"}, status=status.HTTP_400_BAD_REQUEST)
        feature, record, preview, diff, error = _tool_context(request, proposal.tool, proposal.arguments)
        if error:
            proposal.status = "failed"
            proposal.error_message = str(error)[:500]
            proposal.save(update_fields=["status", "error_message", "updated_at"])
            write_audit(
                organization=membership.organization,
                actor=request.user,
                action="ai.tool.failed",
                object_type="tool_call_proposal",
                object_id=proposal.pk,
                metadata={"tool": proposal.tool, "error": str(error)[:200]},
                success=False,
            )
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        if proposal.tool == "feature.record.create":
            record = FeatureRecord.objects.create(
                feature=feature,
                data=proposal.arguments["data"],
                created_by=request.user,
                updated_by=request.user,
            )
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
            result = {"deleted": True, "record_id": record_id}
            action = "feature.record.deleted"
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action=action,
            object_type="feature_record",
            object_id=result.get("id", result.get("record_id", "")),
            metadata={"feature": feature.key, "via_tool": proposal.tool},
        )
        proposal.preview = preview
        proposal.diff = diff
        proposal.result = result
        proposal.status = "confirmed"
        proposal.save(update_fields=["preview", "diff", "result", "status", "updated_at"])
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="ai.tool.confirmed",
            object_type="tool_call_proposal",
            object_id=proposal.pk,
            metadata={"tool": proposal.tool, "risk": proposal.risk},
        )
        return Response(_tool_payload(proposal))


class ToolCallProposalRevokeView(APIView):
    @transaction.atomic
    def post(self, request, proposal_id):
        if not user_has_permission(request, "ai.use"):
            return Response({"detail": "没有使用 AI 的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        proposal = ToolCallProposal.objects.select_for_update().filter(
            organization=membership.organization, id=proposal_id, user=request.user
        ).first()
        if proposal is None:
            return Response({"detail": "方案不存在"}, status=status.HTTP_404_NOT_FOUND)
        if proposal.status != "proposed":
            return Response({"detail": "该工具方案已经处理"}, status=status.HTTP_400_BAD_REQUEST)
        proposal.status = "revoked"
        proposal.save(update_fields=["status", "updated_at"])
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="ai.tool.revoked",
            object_type="tool_call_proposal",
            object_id=proposal.pk,
            metadata={"tool": proposal.tool},
        )
        return Response(_tool_payload(proposal))
