import re
import uuid

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User

from .models import AuditLog, MemberInvitation, Membership, Permission, Role, RolePermission
from .services import (
    PERMISSION_METADATA,
    can_assign_data_scope,
    can_assign_role,
    create_invitation,
    create_organization,
    get_assignable_permissions,
    get_active_organization,
    get_active_membership,
    get_user_memberships,
    normalize_data_scope,
    membership_has_permission,
    organization_path,
    sync_membership_status,
    user_has_permission,
    write_audit,
)


USERNAME_RE = re.compile(r"^\S{2,80}$")


def organization_payload(organization):
    return {
        "id": str(organization.id),
        "name": organization.name,
        "slug": organization.slug,
        "parent_id": str(organization.parent_id) if organization.parent_id else None,
        "parent_name": organization.parent.name if organization.parent_id else None,
        "path": organization_path(organization),
    }


def member_payload(item):
    return {
        "id": item.user_id,
        "username": item.user.username,
        "email": item.user.email or "",
        "display_name": item.user.display_name or item.user.username,
        "contact": item.user.contact,
        "role": item.role.name,
        "role_id": item.role_id,
        "is_owner": item.is_owner,
        "status": item.status,
        "is_active": item.status == "active",
        "invited_at": item.invited_at,
        "accepted_at": item.accepted_at,
        "created_at": item.created_at,
    }


def parse_bool(value):
    if value in (True, 1, "1", "true", "True"):
        return True
    if value in (False, 0, "0", "false", "False"):
        return False
    return None


def role_payload(item):
    member_count = getattr(item, "member_count", None)
    if member_count is None:
        member_count = item.memberships.filter(status="active", is_active=True).count()
    return {
        "id": item.id,
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "is_system": item.is_system,
        "data_scope": item.data_scope or {"mode": "all"},
        "member_count": member_count,
        "permissions": [permission.code for permission in item.permissions.all()],
    }


def parse_role_permissions(membership, values, preserved_codes=None):
    codes = list(dict.fromkeys(values))
    permissions = list(Permission.objects.filter(code__in=codes))
    if len(permissions) != len(codes):
        return None, "包含不存在的权限"
    allowed_codes = set(get_assignable_permissions(membership).values_list("code", flat=True))
    unauthorized_codes = sorted(set(codes) - allowed_codes)
    if unauthorized_codes:
        return None, "不能分配当前账号没有的权限"
    return permissions, None


class OrganizationListView(APIView):
    def get(self, request):
        return Response(
            [
                {
                    **organization_payload(item.organization),
                    "role": item.role.name,
                    "is_owner": item.is_owner,
                }
                for item in get_user_memberships(request.user)
            ]
        )

    def post(self, request):
        raw_name = request.data.get("name", "")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not name or len(name) > 160 or any(ord(char) < 32 for char in name):
            return Response({"detail": "组织名称不能为空"}, status=status.HTTP_400_BAD_REQUEST)
        parent_id = request.data.get("parent_id")
        parent = None
        if parent_id not in (None, "", "null"):
            try:
                parent_uuid = uuid.UUID(str(parent_id))
            except (ValueError, TypeError, AttributeError):
                return Response({"detail": "上级组织编号无效"}, status=status.HTTP_400_BAD_REQUEST)
            parent_membership = get_user_memberships(request.user).filter(organization_id=parent_uuid).first()
            if parent_membership is None:
                return Response({"detail": "无权在该组织下创建子组织"}, status=status.HTTP_403_FORBIDDEN)
            if not membership_has_permission(parent_membership, "organization.manage"):
                return Response({"detail": "没有管理上级组织的权限"}, status=status.HTTP_403_FORBIDDEN)
            parent = parent_membership.organization
        organization = create_organization(user=request.user, name=name, parent=parent)
        return Response(organization_payload(organization), status=status.HTTP_201_CREATED)


class CurrentOrganizationView(APIView):
    def get(self, request):
        organization = get_active_organization(request)
        membership = get_active_membership(request)
        if organization is None or membership is None:
            return Response({"detail": "当前用户没有组织"}, status=status.HTTP_404_NOT_FOUND)
        permission_codes = list(
            Permission.objects.filter(roles__memberships=membership).values_list("code", flat=True).distinct()
        )
        if membership.is_owner or request.user.is_superuser:
            permission_codes = list(Permission.objects.values_list("code", flat=True))
        return Response(
            {
                **organization_payload(organization),
                "role": membership.role.name,
                "is_owner": membership.is_owner,
                "permissions": permission_codes,
            }
        )


class MemberListView(APIView):
    def get(self, request):
        if get_active_membership(request) is None:
            return Response([])
        if not user_has_permission(request, "member.read"):
            return Response({"detail": "没有查看成员的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        members = Membership.objects.select_related("user", "role").filter(
            organization=membership.organization
        )
        return Response([member_payload(item) for item in members])

    @transaction.atomic
    def post(self, request):
        if get_active_membership(request) is None:
            return Response({"detail": "当前用户没有组织"}, status=status.HTTP_404_NOT_FOUND)
        if not user_has_permission(request, "member.manage"):
            return Response({"detail": "没有管理成员的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        username = str(request.data.get("username", request.data.get("email", ""))).strip().casefold()
        display_name = str(request.data.get("display_name", "")).strip()
        contact = str(request.data.get("contact", "")).strip()
        password = str(request.data.get("password", ""))
        role_id = request.data.get("role_id")
        if not USERNAME_RE.fullmatch(username):
            return Response({"detail": "账号必须是 2 到 80 个不能包含空白的字符"}, status=status.HTTP_400_BAD_REQUEST)
        if len(display_name) > 120 or len(contact) > 120:
            return Response({"detail": "姓名和联系方式不能超过 120 个字符"}, status=status.HTTP_400_BAD_REQUEST)
        role = Role.objects.filter(organization=membership.organization, id=role_id).first()
        if role is None:
            return Response({"detail": "角色不存在"}, status=status.HTTP_400_BAD_REQUEST)
        if role.is_system and role.code == "owner":
            return Response({"detail": "不能把所有者角色分配给普通成员"}, status=status.HTTP_400_BAD_REQUEST)
        if not can_assign_role(membership, role):
            return Response({"detail": "不能把权限高于当前账号的角色分配给成员"}, status=status.HTTP_403_FORBIDDEN)
        user = User.objects.filter(username=username).first()
        if user is None:
            if not display_name or not contact:
                return Response({"detail": "新增成员必须填写姓名和联系方式"}, status=status.HTTP_400_BAD_REQUEST)
            if len(password) < 10:
                return Response({"detail": "新成员密码至少需要 10 个字符"}, status=status.HTTP_400_BAD_REQUEST)
            user = User.objects.create_user(
                username=username,
                password=password,
                display_name=display_name,
                contact=contact,
            )
        elif password:
            return Response({"detail": "已有账号不能通过此接口重置密码"}, status=status.HTTP_400_BAD_REQUEST)
        existing = Membership.objects.filter(organization=membership.organization, user=user).first()
        if existing is None and (not (display_name or user.display_name) or not (contact or user.contact)):
            return Response({"detail": "新增成员必须填写姓名和联系方式"}, status=status.HTTP_400_BAD_REQUEST)
        if existing and existing.is_owner:
            return Response({"detail": "所有者不能通过成员接口修改"}, status=status.HTTP_400_BAD_REQUEST)
        if existing:
            existing.role = role
            sync_membership_status(existing, "active", save=False)
            existing.save(update_fields=["role", "status", "is_active"])
            created = False
            target = existing
        else:
            target = Membership.objects.create(organization=membership.organization, user=user, role=role)
            created = True
        if display_name and user.display_name != display_name:
            user.display_name = display_name
            user.save(update_fields=["display_name"])
        if "contact" in request.data and user.contact != contact:
            user.contact = contact
            user.save(update_fields=["contact"])
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="member.added" if created else "member.rejoined",
            object_type="membership",
            object_id=target.pk,
            metadata={"username": user.username, "role": role.code},
        )
        return Response(member_payload(target), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class MemberDetailView(APIView):
    @transaction.atomic
    def patch(self, request, user_id):
        if not user_has_permission(request, "member.manage"):
            return Response({"detail": "没有管理成员的权限"}, status=status.HTTP_403_FORBIDDEN)
        current = get_active_membership(request)
        target = Membership.objects.select_related("user", "role").filter(
            organization=current.organization, user_id=user_id
        ).first()
        if target is None:
            return Response({"detail": "成员不存在"}, status=status.HTTP_404_NOT_FOUND)
        if target.is_owner:
            return Response({"detail": "所有者不能通过成员接口修改"}, status=status.HTTP_400_BAD_REQUEST)
        changes = []
        user_changes = []
        if "role_id" in request.data:
            role = Role.objects.filter(organization=current.organization, id=request.data["role_id"]).first()
            if role is None:
                return Response({"detail": "角色不存在"}, status=status.HTTP_400_BAD_REQUEST)
            if role.is_system and role.code == "owner":
                return Response({"detail": "不能把所有者角色分配给普通成员"}, status=status.HTTP_400_BAD_REQUEST)
            if not can_assign_role(current, role):
                return Response({"detail": "不能把权限高于当前账号的角色分配给成员"}, status=status.HTTP_403_FORBIDDEN)
            target.role = role
            changes.append("role")
        if "is_active" in request.data:
            is_active = parse_bool(request.data["is_active"])
            if is_active is None:
                return Response({"detail": "is_active 必须是布尔值"}, status=status.HTTP_400_BAD_REQUEST)
            sync_membership_status(target, "active" if is_active else "disabled", save=False)
            changes.append("status")
        if "status" in request.data:
            requested_status = request.data["status"]
            if requested_status not in {"active", "disabled"}:
                return Response({"detail": "status 只能是 active 或 disabled"}, status=status.HTTP_400_BAD_REQUEST)
            sync_membership_status(target, requested_status, save=False)
            changes.append("status")
        if "display_name" in request.data:
            display_name = str(request.data["display_name"]).strip()
            if not display_name:
                return Response({"detail": "姓名不能为空"}, status=status.HTTP_400_BAD_REQUEST)
            target.user.display_name = display_name
            user_changes.append("display_name")
        if "contact" in request.data:
            contact = str(request.data["contact"]).strip()
            if not contact:
                return Response({"detail": "联系方式不能为空"}, status=status.HTTP_400_BAD_REQUEST)
            target.user.contact = contact
            user_changes.append("contact")
        if changes:
            fields_to_save = set(changes)
            if "status" in fields_to_save:
                fields_to_save.add("is_active")
            target.save(update_fields=list(fields_to_save))
        if user_changes:
            target.user.save(update_fields=list(set(user_changes)))
        if changes or user_changes:
            audit_action = "member.updated"
            if "status" in changes:
                audit_action = "member.restored" if target.status == "active" else "member.disabled"
            write_audit(
                organization=current.organization,
                actor=request.user,
                action=audit_action,
                object_type="membership",
                object_id=target.pk,
                metadata={"changes": changes + user_changes},
            )
        return Response(member_payload(target))

    @transaction.atomic
    def delete(self, request, user_id):
        if not user_has_permission(request, "member.manage"):
            return Response({"detail": "没有管理成员的权限"}, status=status.HTTP_403_FORBIDDEN)
        current = get_active_membership(request)
        target = Membership.objects.filter(organization=current.organization, user_id=user_id).first()
        if target is None:
            return Response({"detail": "成员不存在"}, status=status.HTTP_404_NOT_FOUND)
        if target.is_owner:
            return Response({"detail": "所有者不能被移除"}, status=status.HTTP_400_BAD_REQUEST)
        target.delete()
        write_audit(
            organization=current.organization,
            actor=request.user,
            action="member.removed",
            object_type="membership",
            object_id=user_id,
            metadata={},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemberBatchRoleView(APIView):
    """Assign one existing role to several members atomically."""

    @transaction.atomic
    def post(self, request):
        if not user_has_permission(request, "role.manage"):
            return Response({"detail": "没有批量授权的权限"}, status=status.HTTP_403_FORBIDDEN)
        current = get_active_membership(request)
        user_ids = request.data.get("user_ids")
        if not isinstance(user_ids, list) or not user_ids or len(user_ids) > 200:
            return Response({"detail": "user_ids 必须是 1 到 200 项的数组"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user_ids = list(dict.fromkeys(int(item) for item in user_ids))
        except (TypeError, ValueError):
            return Response({"detail": "user_ids 必须是用户编号数组"}, status=status.HTTP_400_BAD_REQUEST)
        role = Role.objects.filter(organization=current.organization, id=request.data.get("role_id")).first()
        if role is None:
            return Response({"detail": "角色不存在"}, status=status.HTTP_400_BAD_REQUEST)
        if role.is_system and role.code == "owner":
            return Response({"detail": "不能批量分配所有者角色"}, status=status.HTTP_400_BAD_REQUEST)
        if not can_assign_role(current, role):
            return Response({"detail": "不能分配权限高于当前账号的角色"}, status=status.HTTP_403_FORBIDDEN)
        targets = list(
            Membership.objects.select_for_update().select_related("user", "role").filter(
                organization=current.organization, user_id__in=user_ids
            )
        )
        if len(targets) != len(user_ids):
            return Response({"detail": "包含不存在的组织成员"}, status=status.HTTP_404_NOT_FOUND)
        if any(item.is_owner for item in targets):
            return Response({"detail": "所有者不能通过批量授权修改"}, status=status.HTTP_400_BAD_REQUEST)
        for target in targets:
            target.role = role
            target.save(update_fields=["role"])
        write_audit(
            organization=current.organization,
            actor=request.user,
            action="member.roles.batch_updated",
            object_type="membership",
            object_id=current.organization.pk,
            metadata={"user_ids": user_ids, "role_id": role.pk, "role": role.code},
        )
        return Response({"updated": [member_payload(item) for item in targets], "role": role_payload(role)})


class MemberInvitationListView(APIView):
    def get(self, request):
        if not user_has_permission(request, "member.manage"):
            return Response({"detail": "没有管理成员的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        now = timezone.now()
        MemberInvitation.objects.filter(
            organization=membership.organization, status="pending", expires_at__lte=now
        ).update(status="expired")
        invitations = MemberInvitation.objects.select_related("user", "role").filter(
            organization=membership.organization, status="pending"
        )
        return Response(
            [
                {
                    "id": item.id,
                    "username": item.user.username,
                    "display_name": item.user.display_name or item.user.username,
                    "role": item.role.name,
                    "role_id": item.role_id,
                    "expires_at": item.expires_at,
                    "created_at": item.created_at,
                    "status": item.status,
                }
                for item in invitations
            ]
        )

    @transaction.atomic
    def post(self, request):
        if not user_has_permission(request, "member.manage"):
            return Response({"detail": "没有管理成员的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        username = str(request.data.get("username", "")).strip().casefold()
        display_name = str(request.data.get("display_name", "")).strip()
        contact = str(request.data.get("contact", "")).strip()
        role_id = request.data.get("role_id")
        if not USERNAME_RE.fullmatch(username):
            return Response({"detail": "账号必须是 2 到 80 个不能包含空白的字符"}, status=status.HTTP_400_BAD_REQUEST)
        if len(display_name) > 120 or len(contact) > 120:
            return Response({"detail": "姓名和联系方式不能超过 120 个字符"}, status=status.HTTP_400_BAD_REQUEST)
        role = Role.objects.filter(organization=membership.organization, id=role_id).first()
        if role is None:
            return Response({"detail": "角色不存在"}, status=status.HTTP_400_BAD_REQUEST)
        if role.code == "owner":
            return Response({"detail": "不能把所有者角色分配给普通成员"}, status=status.HTTP_400_BAD_REQUEST)
        if not can_assign_role(membership, role):
            return Response({"detail": "不能把权限高于当前账号的角色分配给成员"}, status=status.HTTP_403_FORBIDDEN)
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"display_name": display_name, "contact": contact, "is_active": True},
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        else:
            if display_name and user.display_name != display_name:
                user.display_name = display_name
            if contact and user.contact != contact:
                user.contact = contact
            if display_name or contact:
                user.save(update_fields=["display_name", "contact"])
            user.set_unusable_password()
            user.save(update_fields=["password"])
        target, _ = Membership.objects.get_or_create(
            organization=membership.organization,
            user=user,
            defaults={
                "role": role,
                "status": "invited",
                "is_active": False,
                "invited_at": timezone.now(),
                "invited_by": request.user,
            },
        )
        if target.is_owner:
            return Response({"detail": "所有者不能通过邀请接口修改"}, status=status.HTTP_400_BAD_REQUEST)
        target.role = role
        target.invited_at = timezone.now()
        target.invited_by = request.user
        sync_membership_status(target, "invited", save=False)
        target.save(update_fields=["role", "status", "is_active", "invited_at", "invited_by"])
        invitation, raw_token = create_invitation(
            organization=membership.organization,
            user=user,
            role=role,
            created_by=request.user,
        )
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="member.invited",
            object_type="member_invitation",
            object_id=invitation.pk,
            metadata={"username": user.username, "role": role.code},
        )
        return Response(
            {
                "id": invitation.id,
                "username": user.username,
                "role": role.name,
                "expires_at": invitation.expires_at,
                "token": raw_token,
                "accept_url": f"/api/auth/invitations/{raw_token}/accept/",
            },
            status=status.HTTP_201_CREATED,
        )


class MemberInvitationDetailView(APIView):
    @transaction.atomic
    def delete(self, request, invitation_id):
        if not user_has_permission(request, "member.manage"):
            return Response({"detail": "没有管理成员的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        invitation = MemberInvitation.objects.filter(
            id=invitation_id, organization=membership.organization, status="pending"
        ).first()
        if invitation is None:
            return Response({"detail": "邀请不存在"}, status=status.HTTP_404_NOT_FOUND)
        invitation.status = "revoked"
        invitation.save(update_fields=["status"])
        target = Membership.objects.filter(organization=membership.organization, user=invitation.user).first()
        if target and not target.is_owner and target.status == "invited":
            target.delete()
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="member.invitation.revoked",
            object_type="member_invitation",
            object_id=invitation.pk,
            metadata={"username": invitation.user.username},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class TransferOwnerView(APIView):
    @transaction.atomic
    def post(self, request):
        current = get_active_membership(request)
        if current is None or not current.is_owner:
            return Response({"detail": "只有所有者可以转移所有权"}, status=status.HTTP_403_FORBIDDEN)
        if request.data.get("confirm") is not True:
            return Response({"detail": "请确认所有权转移"}, status=status.HTTP_400_BAD_REQUEST)
        target = Membership.objects.select_for_update().select_related("user").filter(
            organization=current.organization,
            user_id=request.data.get("user_id"),
            status="active",
        ).first()
        if target is None:
            return Response({"detail": "目标成员不存在"}, status=status.HTTP_404_NOT_FOUND)
        if target.pk == current.pk:
            return Response({"detail": "不能转移给自己"}, status=status.HTTP_400_BAD_REQUEST)
        owner_role = Role.objects.get(organization=current.organization, code="owner")
        admin_role = Role.objects.get(organization=current.organization, code="admin")
        current.is_owner = False
        current.role = admin_role
        current.save(update_fields=["is_owner", "role"])
        target.is_owner = True
        target.role = owner_role
        target.save(update_fields=["is_owner", "role"])
        write_audit(
            organization=current.organization,
            actor=request.user,
            action="organization.owner.transferred",
            object_type="membership",
            object_id=target.pk,
            metadata={"from_user_id": current.user_id, "to_user_id": target.user_id},
        )
        return Response({"from_user_id": current.user_id, "to_user_id": target.user_id})


class LeaveOrganizationView(APIView):
    @transaction.atomic
    def post(self, request):
        current = get_active_membership(request)
        if current is None:
            return Response({"detail": "当前用户没有组织"}, status=status.HTTP_404_NOT_FOUND)
        if current.is_owner:
            return Response({"detail": "所有者必须先转移所有权"}, status=status.HTTP_400_BAD_REQUEST)
        organization = current.organization
        current.delete()
        request.session.pop("bixi_active_organization_id", None)
        request.session.modified = True
        write_audit(
            organization=organization,
            actor=request.user,
            action="member.left",
            object_type="membership",
            object_id=request.user.pk,
            metadata={},
        )
        return Response({"status": "left"})


class RoleListView(APIView):
    def get(self, request):
        if not user_has_permission(request, "role.manage"):
            return Response({"detail": "没有查看角色的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        roles = (
            Role.objects.prefetch_related("permissions")
            .filter(organization=membership.organization)
            .annotate(member_count=Count("memberships", filter=Q(memberships__status="active", memberships__is_active=True)))
        )
        return Response([role_payload(item) for item in roles])

    @transaction.atomic
    def post(self, request):
        if not user_has_permission(request, "role.manage"):
            return Response({"detail": "没有管理角色的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        code = str(request.data.get("code", "")).strip()
        name = str(request.data.get("name", "")).strip()
        permission_codes = request.data.get("permissions", [])
        data_scope, data_scope_error = normalize_data_scope(request.data.get("data_scope"))
        if not code or not name or len(name) > 120 or not isinstance(permission_codes, list):
            return Response({"detail": "角色参数不完整"}, status=status.HTTP_400_BAD_REQUEST)
        if not all(isinstance(item, str) for item in permission_codes):
            return Response({"detail": "permissions 必须是字符串数组"}, status=status.HTTP_400_BAD_REQUEST)
        if data_scope_error:
            return Response({"detail": data_scope_error}, status=status.HTTP_400_BAD_REQUEST)
        if not can_assign_data_scope(membership, data_scope):
            return Response({"detail": "不能分配超出当前账号的数据范围"}, status=status.HTTP_403_FORBIDDEN)
        if not code.replace("-", "").replace("_", "").isalnum() or len(code) > 100:
            return Response({"detail": "角色编码格式不正确"}, status=status.HTTP_400_BAD_REQUEST)
        if Role.objects.filter(organization=membership.organization, code=code).exists():
            return Response({"detail": "角色编码已存在"}, status=status.HTTP_400_BAD_REQUEST)
        permissions_found, permission_error = parse_role_permissions(membership, permission_codes)
        if permission_error:
            error_status = status.HTTP_403_FORBIDDEN if permission_error.startswith("不能") else status.HTTP_400_BAD_REQUEST
            return Response({"detail": permission_error}, status=error_status)
        role = Role.objects.create(
            organization=membership.organization,
            code=code,
            name=name,
            description=str(request.data.get("description", "")).strip(),
            data_scope=data_scope,
        )
        RolePermission.objects.bulk_create(
            [RolePermission(role=role, permission=permission) for permission in permissions_found]
        )
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="role.created",
            object_type="role",
            object_id=role.pk,
            metadata={"code": role.code, "permissions": [permission.code for permission in permissions_found]},
        )
        role = (
            Role.objects.prefetch_related("permissions")
            .filter(pk=role.pk)
            .annotate(member_count=Count("memberships", filter=Q(memberships__status="active", memberships__is_active=True)))
            .get()
        )
        return Response(role_payload(role), status=status.HTTP_201_CREATED)


class RoleDetailView(APIView):
    @transaction.atomic
    def patch(self, request, role_id):
        if not user_has_permission(request, "role.manage"):
            return Response({"detail": "没有管理角色的权限"}, status=status.HTTP_403_FORBIDDEN)
        current = get_active_membership(request)
        role = Role.objects.prefetch_related("permissions").filter(
            organization=current.organization, id=role_id
        ).first()
        if role is None:
            return Response({"detail": "角色不存在"}, status=status.HTTP_404_NOT_FOUND)
        if role.is_system:
            return Response({"detail": "系统角色不能编辑"}, status=status.HTTP_400_BAD_REQUEST)
        existing_scope, scope_error = normalize_data_scope(role.data_scope)
        if scope_error or not can_assign_data_scope(current, existing_scope):
            return Response({"detail": "不能管理超出当前账号数据范围的角色"}, status=status.HTTP_403_FORBIDDEN)
        permissions = None
        data_scope = None
        if "permissions" in request.data:
            codes = request.data["permissions"]
            if not isinstance(codes, list):
                return Response({"detail": "permissions 必须是数组"}, status=status.HTTP_400_BAD_REQUEST)
            if not all(isinstance(item, str) for item in codes):
                return Response({"detail": "permissions 必须是字符串数组"}, status=status.HTTP_400_BAD_REQUEST)
            permissions, permission_error = parse_role_permissions(current, codes)
            if permission_error:
                error_status = status.HTTP_403_FORBIDDEN if permission_error.startswith("不能") else status.HTTP_400_BAD_REQUEST
                return Response({"detail": permission_error}, status=error_status)
        if "data_scope" in request.data:
            data_scope, data_scope_error = normalize_data_scope(request.data["data_scope"])
            if data_scope_error:
                return Response({"detail": data_scope_error}, status=status.HTTP_400_BAD_REQUEST)
            if not can_assign_data_scope(current, data_scope):
                return Response({"detail": "不能分配超出当前账号的数据范围"}, status=status.HTTP_403_FORBIDDEN)
        if "name" in request.data:
            name = str(request.data["name"]).strip()
            if not name or len(name) > 120:
                return Response({"detail": "角色名称不能为空且不能超过 120 个字符"}, status=status.HTTP_400_BAD_REQUEST)
            role.name = name
        if "description" in request.data:
            role.description = str(request.data["description"]).strip()
        if data_scope is not None:
            role.data_scope = data_scope
        role.save(update_fields=["name", "description", "data_scope"])
        if permissions is not None:
            role.permissions.set(permissions)
        write_audit(
            organization=current.organization,
            actor=request.user,
            action="role.permissions.updated" if "permissions" in request.data else "role.updated",
            object_type="role",
            object_id=role.pk,
            metadata={"changes": list(request.data.keys())},
        )
        role.refresh_from_db()
        role = (
            Role.objects.prefetch_related("permissions")
            .filter(pk=role.pk)
            .annotate(member_count=Count("memberships", filter=Q(memberships__status="active", memberships__is_active=True)))
            .get()
        )
        return Response(role_payload(role))

    @transaction.atomic
    def delete(self, request, role_id):
        if not user_has_permission(request, "role.manage"):
            return Response({"detail": "没有管理角色的权限"}, status=status.HTTP_403_FORBIDDEN)
        current = get_active_membership(request)
        role = Role.objects.filter(organization=current.organization, id=role_id).first()
        if role is None:
            return Response({"detail": "角色不存在"}, status=status.HTTP_404_NOT_FOUND)
        if role.is_system:
            return Response({"detail": "系统角色不能删除"}, status=status.HTTP_400_BAD_REQUEST)
        if role.memberships.exists():
            return Response({"detail": "角色仍有成员，不能删除"}, status=status.HTTP_400_BAD_REQUEST)
        role.delete()
        write_audit(
            organization=current.organization,
            actor=request.user,
            action="role.deleted",
            object_type="role",
            object_id=role_id,
            metadata={},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoleCopyView(APIView):
    @transaction.atomic
    def post(self, request, role_id):
        if not user_has_permission(request, "role.manage"):
            return Response({"detail": "没有管理角色的权限"}, status=status.HTTP_403_FORBIDDEN)
        current = get_active_membership(request)
        source = Role.objects.prefetch_related("permissions").filter(
            organization=current.organization, id=role_id
        ).first()
        if source is None:
            return Response({"detail": "角色不存在"}, status=status.HTTP_404_NOT_FOUND)
        if not can_assign_role(current, source):
            return Response({"detail": "不能复制权限高于当前账号的角色"}, status=status.HTTP_403_FORBIDDEN)
        code = str(request.data.get("code", f"{source.code}-copy")).strip()
        name = str(request.data.get("name", f"{source.name}副本")).strip()
        if not code or len(code) > 100 or not code.replace("-", "").replace("_", "").isalnum():
            return Response({"detail": "角色编码格式不正确"}, status=status.HTTP_400_BAD_REQUEST)
        if not name or len(name) > 120:
            return Response({"detail": "角色名称不能为空且不能超过 120 个字符"}, status=status.HTTP_400_BAD_REQUEST)
        if Role.objects.filter(organization=current.organization, code=code).exists():
            return Response({"detail": "角色编码已存在"}, status=status.HTTP_400_BAD_REQUEST)
        role = Role.objects.create(
            organization=current.organization,
            code=code,
            name=name,
            description=str(request.data.get("description", source.description)).strip()[:300],
            data_scope=source.data_scope or {"mode": "all"},
        )
        role.permissions.set(source.permissions.all())
        write_audit(
            organization=current.organization,
            actor=request.user,
            action="role.copied",
            object_type="role",
            object_id=role.pk,
            metadata={"source_role_id": source.pk, "source_code": source.code},
        )
        role = Role.objects.prefetch_related("permissions").filter(pk=role.pk).get()
        return Response(role_payload(role), status=status.HTTP_201_CREATED)


class PermissionCatalogView(APIView):
    def get(self, request):
        if not user_has_permission(request, "role.manage"):
            return Response({"detail": "没有查看权限目录的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        assignable_codes = set(get_assignable_permissions(membership).values_list("code", flat=True))
        return Response(
            [
                {
                    **item,
                    **PERMISSION_METADATA.get(
                        item["code"],
                        {"menu_code": "other", "menu_name": "其他", "action": item["name"]},
                    ),
                    "assignable": item["code"] in assignable_codes,
                }
                for item in Permission.objects.values("code", "name", "description")
            ]
        )


class AuditLogListView(APIView):
    def get(self, request):
        if request.user.is_superuser:
            logs = AuditLog.objects.select_related("actor").filter(scope=request.query_params.get("scope", "organization"))
            organization = get_active_organization(request)
            if request.query_params.get("scope", "organization") != "system":
                logs = logs.filter(organization=organization)
        elif not user_has_permission(request, "audit.read"):
            return Response({"detail": "没有查看审计日志的权限"}, status=status.HTTP_403_FORBIDDEN)
        else:
            membership = get_active_membership(request)
            logs = AuditLog.objects.select_related("actor").filter(
                organization=membership.organization, scope="organization"
            )
        for field in ("action", "object_type"):
            value = request.query_params.get(field)
            if value:
                logs = logs.filter(**{field: value})
        actor = request.query_params.get("actor")
        if actor:
            if actor.isdigit():
                logs = logs.filter(actor_id=int(actor))
            else:
                logs = logs.filter(Q(actor__username__icontains=actor) | Q(actor__display_name__icontains=actor))
        if request.query_params.get("success") in {"true", "false", "1", "0"}:
            logs = logs.filter(success=request.query_params.get("success") in {"true", "1"})
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            logs = logs.filter(created_at__date__gte=date_from)
        if date_to:
            logs = logs.filter(created_at__date__lte=date_to)
        try:
            page = max(int(request.query_params.get("page", "1")), 1)
            page_size = min(max(int(request.query_params.get("page_size", "20")), 1), 100)
        except ValueError:
            return Response({"detail": "page 和 page_size 必须是数字"}, status=status.HTTP_400_BAD_REQUEST)
        logs = logs.order_by("-created_at")
        total = logs.count()
        start = (page - 1) * page_size
        logs = logs[start : start + page_size]
        return Response(
            {
                "items": [
                {
                    "id": item.id,
                    "actor": item.actor.display_name or item.actor.email if item.actor else "系统",
                    "action": item.action,
                    "object_type": item.object_type,
                    "object_id": item.object_id,
                    "metadata": item.metadata,
                    "success": item.success,
                    "created_at": item.created_at,
                }
                for item in logs
                ],
                "pagination": {"page": page, "page_size": page_size, "total": total},
            }
        )
