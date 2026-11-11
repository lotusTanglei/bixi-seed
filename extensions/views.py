from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.services import get_active_membership, user_has_permission, write_audit

from .models import ExtensionDraft
from .services import draft_content_hash, inspect_draft, is_utf8_text


def draft_payload(item):
    return {
        "id": item.id, "key": item.key, "name": item.name, "description": item.description,
        "files": item.files, "dependencies": item.dependencies,
        "permission_manifest": item.permission_manifest, "static_checks": item.static_checks,
        "validated_hash": item.validated_hash, "enabled_hash": item.enabled_hash,
        "enabled_by": item.enabled_by_id, "enabled_at": item.enabled_at,
        "isolation_status": item.isolation_status, "status": item.status,
        "execution_status": "not_loaded_or_executed",
        "created_at": item.created_at, "updated_at": item.updated_at,
    }


def inspect_item(item, membership):
    checks = inspect_draft(
        key=item.key, files=item.files, dependencies=item.dependencies,
        permission_manifest=item.permission_manifest, membership=membership,
    )
    checks["content_hash"] = draft_content_hash(item)
    return checks


def save_review(item, checks):
    item.static_checks = checks
    item.validated_hash = checks["content_hash"] if checks["passed"] else ""
    item.isolation_status = "not_executed"
    item.status = "validated" if checks["passed"] else "rejected"
    item.save(update_fields=["static_checks", "validated_hash", "isolation_status", "status", "updated_at"])


def audit_review(request, draft, action, *, success=True, errors=None):
    write_audit(
        organization=draft.organization, actor=request.user, action=action,
        object_type="extension_draft", object_id=draft.pk, success=success,
        metadata={"key": draft.key, "content_hash": draft_content_hash(draft),
                  "permission_manifest": draft.permission_manifest,
                  "execution_status": "not_loaded_or_executed", "errors": (errors or [])[:5]},
    )


class ExtensionDraftListView(APIView):
    def get(self, request):
        if not user_has_permission(request, "feature.manage"):
            return Response({"detail": "没有管理扩展草稿的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        return Response([draft_payload(item) for item in ExtensionDraft.objects.filter(organization=membership.organization)])

    @transaction.atomic
    def post(self, request):
        if not user_has_permission(request, "feature.manage"):
            return Response({"detail": "没有管理扩展草稿的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        draft = ExtensionDraft(
            organization=membership.organization, created_by=request.user,
            key=str(request.data.get("key", "")).strip(),
            name=str(request.data.get("name", "")).strip(),
            description=str(request.data.get("description", "")).strip()[:500],
            files=request.data.get("files", {}), dependencies=request.data.get("dependencies", []),
            permission_manifest=request.data.get("permission_manifest", []),
        )
        checks = inspect_item(draft, membership)
        errors = list(checks["errors"])
        if not is_utf8_text(draft.name) or not draft.name or len(draft.name) > 160:
            errors.append("name 必须是有效 UTF-8 文本，不能为空且不能超过 160 个字符")
        if not is_utf8_text(draft.description):
            errors.append("description 必须是有效 UTF-8 文本")
        if is_utf8_text(draft.key) and ExtensionDraft.objects.filter(organization=membership.organization, key=draft.key).exists():
            errors.append("扩展草稿编码已存在")
        if errors:
            return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)
        draft.save()
        save_review(draft, checks)
        audit_review(request, draft, "extension.draft.created")
        return Response(draft_payload(draft), status=status.HTTP_201_CREATED)


class ExtensionDraftValidateView(APIView):
    @transaction.atomic
    def post(self, request, draft_id):
        if not user_has_permission(request, "feature.manage"):
            return Response({"detail": "没有管理扩展草稿的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        draft = ExtensionDraft.objects.select_for_update().filter(id=draft_id, organization=membership.organization).first()
        if draft is None:
            return Response({"detail": "扩展草稿不存在"}, status=status.HTTP_404_NOT_FOUND)
        if draft.status == "enabled":
            return Response({"detail": "已收录草稿不可重新确认，请创建新的草稿"}, status=status.HTTP_409_CONFLICT)
        checks = inspect_item(draft, membership)
        save_review(draft, checks)
        audit_review(request, draft, "extension.draft.validated", success=checks["passed"], errors=checks["errors"])
        return Response(draft_payload(draft), status=status.HTTP_200_OK if checks["passed"] else status.HTTP_400_BAD_REQUEST)


class ExtensionDraftEnableView(APIView):
    @transaction.atomic
    def post(self, request, draft_id):
        if not user_has_permission(request, "feature.manage"):
            return Response({"detail": "没有管理扩展草稿的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        draft = ExtensionDraft.objects.select_for_update().filter(id=draft_id, organization=membership.organization).first()
        if draft is None:
            return Response({"detail": "扩展草稿不存在"}, status=status.HTTP_404_NOT_FOUND)
        errors = []
        if request.data.get("confirmed") is not True:
            errors.append("必须显式确认收录；草稿代码不会被加载或执行")
        expected_hash = draft_content_hash(draft)
        if draft.status != "validated" or not draft.validated_hash or draft.validated_hash != expected_hash or request.data.get("content_hash") != expected_hash:
            errors.append("草稿内容或校验结果已变化，请重新检查并确认当前内容")
        if errors:
            audit_review(request, draft, "extension.draft.enable_denied", success=False, errors=errors)
            return Response({"detail": errors}, status=status.HTTP_409_CONFLICT)
        checks = inspect_item(draft, membership)
        if not checks["passed"]:
            save_review(draft, checks)
            audit_review(request, draft, "extension.draft.enable_denied", success=False, errors=checks["errors"])
            return Response({"detail": checks["errors"], "draft": draft_payload(draft)}, status=status.HTTP_400_BAD_REQUEST)
        draft.static_checks = checks
        draft.status = "enabled"
        draft.isolation_status = "not_executed"
        draft.enabled_hash = expected_hash
        draft.enabled_by = request.user
        draft.enabled_at = timezone.now()
        draft.save(update_fields=["static_checks", "status", "isolation_status", "enabled_hash", "enabled_by", "enabled_at", "updated_at"])
        audit_review(request, draft, "extension.draft.enabled")
        return Response(draft_payload(draft))
