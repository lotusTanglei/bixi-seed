import json
import logging
import re

from django.db import transaction
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from features.models import Feature
from features.services import validate_manifest
from organizations.services import get_active_membership, user_has_permission, write_audit

from .models import Conversation, FeatureProposal, LLMProviderConfig, Message
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
                yield _event("done", {"message_id": assistant.id})
            except Exception:
                logger.exception("AI completion failed")
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
