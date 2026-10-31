from django.db import connection
from django.http import FileResponse, JsonResponse
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.services import get_active_membership, membership_has_permission

from .models import SiteSettings
from .filekit.uploads import UploadError, store_uploaded_file, upload_root


def health(request):
    try:
        connection.ensure_connection()
    except Exception:
        return JsonResponse(
            {"status": "error", "service": "bixi-seed-core"}, status=503
        )
    return JsonResponse(
        {"status": "ok", "service": "bixi-seed-core", "version": "0.1.0"}
    )


def serialize_site_settings(settings_obj):
    return {
        "site_name": settings_obj.site_name,
        "login_welcome": settings_obj.login_welcome,
        "login_description": settings_obj.login_description,
        "home_title": settings_obj.home_title,
        "home_description": settings_obj.home_description,
        "logo_url": "/api/site-settings/logo/" if settings_obj.logo_path else None,
        "updated_at": settings_obj.updated_at,
    }


class SiteSettingsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(serialize_site_settings(SiteSettings.objects.get_or_create(pk=1)[0]))

    def patch(self, request):
        if not request.user.is_authenticated:
            return Response({"detail": "需要登录"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        if membership is None or not membership_has_permission(membership, "organization.manage"):
            return Response({"detail": "没有管理站点设置的权限"}, status=status.HTTP_403_FORBIDDEN)
        settings_obj, _ = SiteSettings.objects.get_or_create(pk=1)
        allowed = ("site_name", "login_welcome", "login_description", "home_title", "home_description")
        for field in allowed:
            if field in request.data:
                value = str(request.data[field]).strip()
                if not value:
                    return Response({"detail": f"{field} 不能为空"}, status=status.HTTP_400_BAD_REQUEST)
                setattr(settings_obj, field, value)
        if request.FILES.get("logo"):
            try:
                stored = store_uploaded_file(
                    request.FILES["logo"], category="site", allowed_extensions={".png", ".jpg", ".jpeg", ".webp"}
                )
            except UploadError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            settings_obj.logo_path = stored.relative_path
            settings_obj.logo_content_type = stored.content_type
        settings_obj.save()
        return Response(serialize_site_settings(settings_obj))


class SiteLogoView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        settings_obj = SiteSettings.objects.get_or_create(pk=1)[0]
        if not settings_obj.logo_path:
            return Response({"detail": "未设置 Logo"}, status=status.HTTP_404_NOT_FOUND)
        root = upload_root().resolve()
        path = (root / settings_obj.logo_path).resolve()
        if root not in path.parents or not path.exists():
            return Response({"detail": "Logo 不存在"}, status=status.HTTP_404_NOT_FOUND)
        return FileResponse(path.open("rb"), content_type=settings_obj.logo_content_type or "application/octet-stream")
