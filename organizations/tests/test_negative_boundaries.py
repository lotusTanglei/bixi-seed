from django.test import TestCase

from accounts.models import User
from organizations.models import Membership, Permission, Role
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class OrganizationNegativeBoundaryTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        self.owner = User.objects.create_user("boundary-owner", "boundary-password-123")
        self.organization = create_organization(user=self.owner, name="边界组织")

    def test_user_without_membership_gets_explicit_empty_or_not_found(self):
        user = User.objects.create_user("no-membership", "boundary-password-123")
        client = self.client.__class__()
        client.force_login(user)
        self.assertEqual(client.get("/api/organizations/current/").status_code, 404)
        self.assertEqual(client.get("/api/organizations/members/").json(), [])

    def test_permission_boundaries_are_forbidden(self):
        role = Role.objects.get(organization=self.organization, code="member")
        user = User.objects.create_user("ordinary-boundary", "boundary-password-123")
        Membership.objects.create(organization=self.organization, user=user, role=role)
        client = self.client.__class__()
        client.force_login(user)
        self.assertEqual(client.get("/api/organizations/roles/").status_code, 403)
        self.assertEqual(client.get("/api/organizations/audit-logs/").status_code, 403)
        self.assertEqual(client.get("/api/ai/config/").status_code, 403)

    def test_role_manager_cannot_grant_permission_not_in_own_role(self):
        role = Role.objects.create(organization=self.organization, code="limited-manager", name="受限管理员")
        role.permissions.add(Permission.objects.get(code="role.manage"))
        user = User.objects.create_user("limited-manager", "boundary-password-123")
        Membership.objects.create(organization=self.organization, user=user, role=role)
        client = self.client.__class__()
        client.force_login(user)
        response = client.post(
            "/api/organizations/roles/",
            {"code": "unsafe", "name": "越权", "permissions": ["ai.configure"]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
