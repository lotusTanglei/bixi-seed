from django.test import TestCase

from accounts.models import User
from features.models import Feature
from organizations.models import Permission
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class OrganizationAccessTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner@example.com", "test-password-123")
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        self.organization = create_organization(user=self.user, name="Test Organization")

    def test_owner_can_read_current_organization(self):
        self.client.force_login(self.user)
        response = self.client.get("/api/organizations/current/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Test Organization")
        self.assertIn("ai.use", response.json()["permissions"])

    def test_organization_switch_requires_membership(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/api/auth/switch-organization/",
            {"organization_id": "00000000-0000-0000-0000-000000000000"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_feature_list_is_scoped_to_the_active_organization(self):
        other_user = User.objects.create_user("other@example.com", "test-password-123")
        other_organization = create_organization(user=other_user, name="Other Organization")
        Feature.objects.create(
            organization=other_organization,
            key="other-feature",
            name="Other Feature",
            status="published",
            created_by=other_user,
        )
        self.client.force_login(self.user)

        response = self.client.get("/api/features/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
