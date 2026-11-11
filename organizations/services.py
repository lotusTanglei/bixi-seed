import hashlib
import secrets
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import AuditLog, MemberInvitation, Membership, Organization, Permission, Role


ACTIVE_ORGANIZATION_SESSION_KEY = "bixi_active_organization_id"

DEFAULT_PERMISSIONS = [
    ("organization.manage", "管理组织", "修改组织基础信息"),
    ("member.read", "查看成员", "查看组织成员"),
    ("member.manage", "管理成员", "邀请、停用和移除成员"),
    ("role.manage", "管理角色", "创建角色并分配权限"),
    ("ai.use", "使用 AI", "创建对话并调用模型"),
    ("ai.configure", "配置 AI", "配置模型服务和 API Key"),
    ("feature.manage", "管理功能", "创建、发布和停用业务功能"),
    ("feature.read", "查看功能数据", "查看已发布功能和业务数据"),
    ("feature.create", "创建功能数据", "创建业务功能数据"),
    ("feature.update", "修改功能数据", "修改业务功能数据"),
    ("feature.delete", "删除功能数据", "删除业务功能数据"),
    ("audit.read", "查看审计日志", "查看组织操作审计记录"),
]

PERMISSION_METADATA = {
    "organization.manage": {"menu_code": "organizations", "menu_name": "组织权限", "action": "组织设置"},
    "member.read": {"menu_code": "organizations", "menu_name": "组织权限", "action": "查看成员"},
    "member.manage": {"menu_code": "organizations", "menu_name": "组织权限", "action": "管理成员"},
    "role.manage": {"menu_code": "organizations", "menu_name": "组织权限", "action": "管理角色"},
    "audit.read": {"menu_code": "organizations", "menu_name": "组织权限", "action": "查看审计"},
    "ai.use": {"menu_code": "ai", "menu_name": "AI 助手", "action": "使用 AI"},
    "ai.configure": {"menu_code": "ai", "menu_name": "AI 助手", "action": "配置 AI"},
    "feature.manage": {"menu_code": "features", "menu_name": "业务功能", "action": "管理功能"},
    "feature.read": {"menu_code": "features", "menu_name": "业务功能", "action": "查看数据"},
    "feature.create": {"menu_code": "features", "menu_name": "业务功能", "action": "创建数据"},
    "feature.update": {"menu_code": "features", "menu_name": "业务功能", "action": "修改数据"},
    "feature.delete": {"menu_code": "features", "menu_name": "业务功能", "action": "删除数据"},
}

PERMISSION_FALLBACKS = {
    "member.read": {"member.read", "member.manage"},
    "feature.read": {"feature.read", "feature.manage"},
}

DATA_SCOPE_MODES = {"all", "own"}


def normalize_data_scope(value):
    """Validate the small, explicit E5 data-scope contract."""
    if value in (None, {}):
        return {"mode": "all"}, None
    if not isinstance(value, dict):
        return None, "data_scope 必须是对象"
    mode = value.get("mode", "all")
    if mode not in DATA_SCOPE_MODES or set(value) - {"mode"}:
        return None, "data_scope.mode 只能是 all 或 own"
    return {"mode": mode}, None


def membership_data_scope(membership):
    scope, error = normalize_data_scope(getattr(membership.role, "data_scope", None))
    return scope if error is None else {"mode": "own"}


def can_assign_data_scope(membership, scope):
    if membership.is_owner or membership.user.is_superuser:
        return True
    return membership_data_scope(membership)["mode"] == "all" or scope["mode"] == "own"


def ensure_default_permissions():
    for code, name, description in DEFAULT_PERMISSIONS:
        Permission.objects.get_or_create(code=code, defaults={"name": name, "description": description})


def get_user_memberships(user):
    if not user.is_authenticated:
        return Membership.objects.none()
    return Membership.objects.select_related("organization", "organization__parent", "role").filter(
        user=user, status="active", is_active=True
    )


def get_active_organization(request):
    if not request.user.is_authenticated:
        return None
    memberships = get_user_memberships(request.user)
    active_id = request.session.get(ACTIVE_ORGANIZATION_SESSION_KEY)
    membership = memberships.filter(organization_id=active_id).first() if active_id else None
    if membership is None:
        membership = memberships.first()
        if membership is not None:
            request.session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(membership.organization_id)
            request.session.modified = True
    if membership is None:
        return None
    request.active_membership = membership
    request.active_organization = membership.organization
    return membership.organization


def get_active_membership(request):
    if get_active_organization(request) is None:
        return None
    return getattr(request, "active_membership", None)


def get_membership_permissions(membership):
    if membership.is_owner or membership.user.is_superuser:
        return list(Permission.objects.values_list("code", flat=True))
    return list(membership.role.permissions.values_list("code", flat=True))


def get_assignable_permissions(membership):
    """返回当前操作者可以授予角色的权限目录。"""
    queryset = Permission.objects.all()
    if membership.is_owner or membership.user.is_superuser:
        return queryset
    return queryset.filter(code__in=get_membership_permissions(membership))


def can_assign_role(membership, role):
    if membership.is_owner or membership.user.is_superuser:
        return True
    actor_permissions = set(get_membership_permissions(membership))
    role_permissions = set(role.permissions.values_list("code", flat=True))
    role_scope, error = normalize_data_scope(role.data_scope)
    return error is None and role_permissions.issubset(actor_permissions) and can_assign_data_scope(membership, role_scope)


def membership_has_permission(membership, permission_code):
    if membership.is_owner or membership.user.is_superuser:
        return True
    allowed_codes = PERMISSION_FALLBACKS.get(permission_code, {permission_code})
    return membership.role.permissions.filter(code__in=allowed_codes).exists()


def user_has_permission(request, permission_code):
    membership = get_active_membership(request)
    if membership is None:
        return False
    return membership_has_permission(membership, permission_code)


def organization_path(organization):
    names = []
    current = organization
    visited = set()
    while current is not None and current.pk not in visited:
        names.append(current.name)
        visited.add(current.pk)
        current = current.parent if current.parent_id else None
    return " / ".join(reversed(names))


def unique_slug(name):
    base = slugify(name) or f"organization-{uuid.uuid4().hex[:8]}"
    value = base
    index = 2
    while Organization.objects.filter(slug=value).exists():
        value = f"{base}-{index}"
        index += 1
    return value


def write_audit(
    *,
    organization=None,
    actor,
    action,
    object_type,
    object_id="",
    metadata=None,
    success=True,
    scope=None,
):
    if scope is None:
        scope = "organization" if organization is not None else "system"
    return AuditLog.objects.create(
        organization=organization,
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        metadata=metadata or {},
        success=success,
        scope=scope,
    )


def sync_membership_status(membership, status, *, save=True):
    if status not in {"invited", "active", "disabled"}:
        raise ValueError("无效的成员状态")
    membership.status = status
    membership.is_active = status == "active"
    if save:
        membership.save(update_fields=["status", "is_active"])
    return membership


def create_invitation(*, organization, user, role, created_by, expires_in_days=7):
    now = timezone.now()
    existing = MemberInvitation.objects.filter(
        organization=organization,
        user=user,
        status="pending",
    ).first()
    if existing:
        existing.status = "revoked"
        existing.save(update_fields=["status"])
    raw_token = secrets.token_urlsafe(32)
    token_digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    invitation = MemberInvitation.objects.create(
        organization=organization,
        user=user,
        role=role,
        token=token_digest,
        expires_at=now + timedelta(days=expires_in_days),
        created_by=created_by,
    )
    return invitation, raw_token


def find_invitation(raw_token, *, for_update=False):
    if not raw_token:
        return None
    digest = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
    queryset = MemberInvitation.objects.select_related("organization", "user", "role")
    if for_update:
        queryset = queryset.select_for_update()
    invitation = queryset.filter(token=digest).first()
    if invitation and invitation.status == "pending" and invitation.expires_at <= timezone.now():
        invitation.status = "expired"
        invitation.save(update_fields=["status"])
        return None
    return invitation


@transaction.atomic
def create_organization(*, user, name, parent=None):
    ensure_default_permissions()
    organization = Organization.objects.create(
        name=name,
        slug=unique_slug(name),
        parent=parent,
        created_by=user,
    )
    owner_role = Role.objects.create(
        organization=organization,
        code="owner",
        name="所有者",
        description="组织的完整管理权限",
        is_system=True,
    )
    owner_role.permissions.set(Permission.objects.all())
    admin_role = Role.objects.create(
        organization=organization,
        code="admin",
        name="管理员",
        description="组织业务和权限的日常管理权限",
        is_system=True,
    )
    admin_role.permissions.set(Permission.objects.all())
    member_role = Role.objects.create(
        organization=organization,
        code="member",
        name="成员",
        description="可以查看组织和已发布业务功能",
        is_system=True,
    )
    member_role.permissions.set(Permission.objects.filter(code__in=["member.read", "feature.read", "ai.use"]))
    Membership.objects.create(
        organization=organization,
        user=user,
        role=owner_role,
        is_owner=True,
    )
    write_audit(
        organization=organization,
        actor=user,
        action="organization.created",
        object_type="organization",
        object_id=organization.pk,
        metadata={"name": organization.name},
    )
    return organization
