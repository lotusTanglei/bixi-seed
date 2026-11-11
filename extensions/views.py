from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.services import get_active_membership, user_has_permission, write_audit

from .models import ExtensionDraft
from .services import checks_payload, validate_draft


def draft_payload(item):
    return {
        "id": item.id,
        "key": item.key,
        "name": item.name,
        "description": item.description,
        "files": item.files,
        "dependencies": item.dependencies,
        "static_checks": item.static_checks,
        "isolation_status": item.isolation_status,
        "status": item.status,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


class ExtensionDraftListView(APIView):
    def get(self, request):
        if not user_has_permission(request, "feature.manage"):
            return Response({"detail": "没有管理扩展草稿的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        drafts = ExtensionDraft.objects.filter(organization=membership.organization)
        return Response([draft_payload(item) for item in drafts])

    @transaction.atomic
    def post(self, request):
        if not user_has_permission(request, "feature.manage"):
            return Response({"detail": "没有管理扩展草稿的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        key = str(request.data.get("key", "")).strip()
        name = str(request.data.get("name", "")).strip()
        files = request.data.get("files", {})
        dependencies = request.data.get("dependencies", [])
        errors = validate_draft(key=key, files=files, dependencies=dependencies)
        if not name or len(name) > 160:
            errors.append("name 不能为空且不能超过 160 个字符")
        if ExtensionDraft.objects.filter(organization=membership.organization, key=key).exists():
            errors.append("扩展草稿编码已存在")
        if errors:
            return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)
        checks = checks_payload([])
        draft = ExtensionDraft.objects.create(
            organization=membership.organization,
            created_by=request.user,
            key=key,
            name=name,
            description=str(request.data.get("description", "")).strip()[:500],
            files=files,
            dependencies=dependencies,
            static_checks=checks,
            isolation_status="ready",
            status="validated",
        )
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="extension.draft.created",
            object_type="extension_draft",
            object_id=draft.pk,
            metadata={"key": key, "isolation_status": draft.isolation_status},
        )
        return Response(draft_payload(draft), status=status.HTTP_201_CREATED)


class ExtensionDraftValidateView(APIView):
    @transaction.atomic
    def post(self, request, draft_id):
        if not user_has_permission(request, "feature.manage"):
            return Response({"detail": "没有管理扩展草稿的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        draft = ExtensionDraft.objects.filter(id=draft_id, organization=membership.organization).first()
        if draft is None:
            return Response({"detail": "扩展草稿不存在"}, status=status.HTTP_404_NOT_FOUND)
        errors = validate_draft(key=draft.key, files=draft.files, dependencies=draft.dependencies)
        checks = checks_payload(errors)
        draft.static_checks = checks
        draft.isolation_status = "ready" if not errors else "blocked"
        draft.status = "validated" if not errors else "rejected"
        draft.save(update_fields=["static_checks", "isolation_status", "status", "updated_at"])
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="extension.draft.validated",
            object_type="extension_draft",
            object_id=draft.pk,
            metadata={"passed": not errors, "errors": errors[:5]},
            success=not errors,
        )
        return Response(draft_payload(draft), status=status.HTTP_200_OK if not errors else status.HTTP_400_BAD_REQUEST)
