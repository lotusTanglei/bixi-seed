from django.urls import path

from .views import (
    CurrentOrganizationView,
    AuditLogListView,
    MemberListView,
    MemberDetailView,
    MemberBatchRoleView,
    OrganizationListView,
    PermissionCatalogView,
    RoleListView,
    RoleDetailView,
    RoleCopyView,
    MemberInvitationListView,
    MemberInvitationDetailView,
    TransferOwnerView,
    LeaveOrganizationView,
)


urlpatterns = [
    path("", OrganizationListView.as_view(), name="organization-list"),
    path("current/", CurrentOrganizationView.as_view(), name="organization-current"),
    path("members/", MemberListView.as_view(), name="member-list"),
    path("members/<int:user_id>/", MemberDetailView.as_view(), name="member-detail"),
    path("members/batch-role/", MemberBatchRoleView.as_view(), name="member-batch-role"),
    path("invitations/", MemberInvitationListView.as_view(), name="member-invitation-list"),
    path("invitations/<int:invitation_id>/", MemberInvitationDetailView.as_view(), name="member-invitation-detail"),
    path("transfer-owner/", TransferOwnerView.as_view(), name="transfer-owner"),
    path("leave/", LeaveOrganizationView.as_view(), name="organization-leave"),
    path("roles/", RoleListView.as_view(), name="role-list"),
    path("roles/<int:role_id>/", RoleDetailView.as_view(), name="role-detail"),
    path("roles/<int:role_id>/copy/", RoleCopyView.as_view(), name="role-copy"),
    path("permissions/", PermissionCatalogView.as_view(), name="permission-catalog"),
    path("audit-logs/", AuditLogListView.as_view(), name="audit-log-list"),
]
