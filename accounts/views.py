from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.services import (
    get_active_organization,
    get_membership_permissions,
    get_user_memberships,
    organization_path,
)


def serialize_user(user):
    return {
        "id": user.pk,
        "username": user.username,
        # email 仅作为兼容字段返回，新账号可以没有邮箱。
        "email": user.email or (user.username if "@" in user.username else ""),
        "display_name": user.display_name or user.username,
        "contact": user.contact,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
    }


def serialize_organization(membership):
    return {
        "id": str(membership.organization_id),
        "name": membership.organization.name,
        "parent_id": str(membership.organization.parent_id) if membership.organization.parent_id else None,
        "parent_name": membership.organization.parent.name if membership.organization.parent_id else None,
        "path": organization_path(membership.organization),
        "role": membership.role.name,
        "is_owner": membership.is_owner,
        "permissions": get_membership_permissions(membership),
    }


class CsrfView(APIView):
    permission_classes = [permissions.AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return JsonResponse({"status": "ok"})


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = str(request.data.get("username", request.data.get("email", ""))).strip().casefold()
        password = request.data.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response({"detail": "账号或密码不正确"}, status=status.HTTP_400_BAD_REQUEST)
        if not user.is_active:
            return Response({"detail": "用户已被停用"}, status=status.HTTP_403_FORBIDDEN)
        login(request, user)
        memberships = get_user_memberships(user)
        active = get_active_organization(request)
        return Response(
            {
                "user": serialize_user(user),
                "organizations": [serialize_organization(item) for item in memberships],
                "active_organization": str(active.pk) if active else None,
            }
        )


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response({"status": "ok"})


class MeView(APIView):
    def get(self, request):
        memberships = get_user_memberships(request.user)
        active = get_active_organization(request)
        return Response(
            {
                "user": serialize_user(request.user),
                "organizations": [serialize_organization(item) for item in memberships],
                "active_organization": str(active.pk) if active else None,
            }
        )


class SwitchOrganizationView(APIView):
    def post(self, request):
        organization_id = request.data.get("organization_id")
        membership = next(
            (
                item
                for item in get_user_memberships(request.user)
                if str(item.organization_id) == str(organization_id)
            ),
            None,
        )
        if membership is None:
            return Response({"detail": "无权访问该组织"}, status=status.HTTP_403_FORBIDDEN)
        request.session["bixi_active_organization_id"] = str(membership.organization_id)
        request.session.modified = True
        return Response({"active_organization": serialize_organization(membership)})
