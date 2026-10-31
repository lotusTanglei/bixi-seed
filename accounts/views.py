from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.services import (
    find_invitation,
    get_active_organization,
    get_membership_permissions,
    get_user_memberships,
    organization_path,
    sync_membership_status,
    write_audit,
)
from organizations.models import Membership


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
            from .models import User

            disabled_user = User.objects.filter(username=username, is_active=False).first()
            if disabled_user:
                write_audit(
                    organization=None,
                    actor=disabled_user,
                    action="auth.login.failed",
                    object_type="user",
                    object_id=disabled_user.pk,
                    metadata={"reason": "user_disabled"},
                    success=False,
                    scope="system",
                )
                return Response({"detail": "用户已被停用"}, status=status.HTTP_403_FORBIDDEN)
            write_audit(
                organization=None,
                actor=None,
                action="auth.login.failed",
                object_type="user",
                metadata={"username": username[:80]},
                success=False,
                scope="system",
            )
            return Response({"detail": "账号或密码不正确"}, status=status.HTTP_400_BAD_REQUEST)
        if not user.is_active:
            write_audit(
                organization=None,
                actor=user,
                action="auth.login.failed",
                object_type="user",
                object_id=user.pk,
                metadata={"reason": "user_disabled"},
                success=False,
                scope="system",
            )
            return Response({"detail": "用户已被停用"}, status=status.HTTP_403_FORBIDDEN)
        if Membership.objects.filter(user=user).exists() and not Membership.objects.filter(
            user=user, status="active", is_active=True
        ).exists():
            write_audit(
                organization=None,
                actor=user,
                action="auth.login.failed",
                object_type="user",
                object_id=user.pk,
                metadata={"reason": "membership_disabled"},
                success=False,
                scope="system",
            )
            return Response({"detail": "用户没有可用的组织成员关系"}, status=status.HTTP_403_FORBIDDEN)
        login(request, user)
        memberships = get_user_memberships(user)
        active = get_active_organization(request)
        write_audit(
            organization=active,
            actor=user,
            action="auth.login.succeeded",
            object_type="user",
            object_id=user.pk,
            metadata={},
        )
        return Response(
            {
                "user": serialize_user(user),
                "organizations": [serialize_organization(item) for item in memberships],
                "active_organization": str(active.pk) if active else None,
            }
        )


class LogoutView(APIView):
    def post(self, request):
        actor = request.user if request.user.is_authenticated else None
        organization = get_active_organization(request) if actor else None
        logout(request)
        write_audit(
            organization=organization,
            actor=actor,
            action="auth.logout",
            object_type="user",
            object_id=actor.pk if actor else "",
            metadata={},
        )
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
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="organization.switched",
            object_type="organization",
            object_id=membership.organization_id,
            metadata={},
        )
        return Response({"active_organization": serialize_organization(membership)})


class InvitationAcceptView(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request, token):
        invitation = find_invitation(token, for_update=True)
        if invitation is None or invitation.status != "pending":
            return Response({"detail": "邀请不存在、已过期或已使用"}, status=status.HTTP_400_BAD_REQUEST)
        password = str(request.data.get("password", ""))
        if len(password) < 10:
            return Response({"detail": "密码至少需要 10 个字符"}, status=status.HTTP_400_BAD_REQUEST)
        user = invitation.user
        user.set_password(password)
        user.is_active = True
        user.save(update_fields=["password", "is_active"])
        membership, _ = Membership.objects.get_or_create(
            organization=invitation.organization,
            user=user,
            defaults={"role": invitation.role, "status": "invited", "is_active": False},
        )
        membership.role = invitation.role
        membership.invited_at = membership.invited_at or invitation.created_at
        membership.accepted_at = timezone.now()
        sync_membership_status(membership, "active", save=False)
        membership.save(
            update_fields=["role", "status", "is_active", "invited_at", "accepted_at"]
        )
        invitation.status = "accepted"
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["status", "accepted_at"])
        login(request, user)
        request.session["bixi_active_organization_id"] = str(invitation.organization_id)
        request.session.modified = True
        write_audit(
            organization=invitation.organization,
            actor=user,
            action="member.invitation.accepted",
            object_type="membership",
            object_id=membership.pk,
            metadata={"username": user.username, "role": invitation.role.code},
        )
        return Response(
            {
                "status": "accepted",
                "user": serialize_user(user),
                "active_organization": str(invitation.organization_id),
            },
            status=status.HTTP_200_OK,
        )
