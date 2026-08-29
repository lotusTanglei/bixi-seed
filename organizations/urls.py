from django.urls import path

from .views import (
    CurrentOrganizationView,
    AuditLogListView,
    MemberListView,
    MemberDetailView,
    OrganizationListView,
    PermissionCatalogView,
    RoleListView,
    RoleDetailView,
)


urlpatterns = [
    path("", OrganizationListView.as_view(), name="organization-list"),
    path("current/", CurrentOrganizationView.as_view(), name="organization-current"),
    path("members/", MemberListView.as_view(), name="member-list"),
    path("members/<int:user_id>/", MemberDetailView.as_view(), name="member-detail"),
    path("roles/", RoleListView.as_view(), name="role-list"),
    path("roles/<int:role_id>/", RoleDetailView.as_view(), name="role-detail"),
    path("permissions/", PermissionCatalogView.as_view(), name="permission-catalog"),
    path("audit-logs/", AuditLogListView.as_view(), name="audit-log-list"),
]
