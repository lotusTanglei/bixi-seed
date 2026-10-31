from django.test import TestCase

from accounts.models import User
from organizations.models import AuditLog, Membership, Permission
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class NegativeAuthApiTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        self.user = User.objects.create_user("negative-login", "test-password-123")
        self.organization = create_organization(user=self.user, name="认证负向测试")

    def test_protected_endpoint_requires_authentication(self):
        response = self.client.get("/api/organizations/current/")
        self.assertIn(response.status_code, {401, 403})

    def test_wrong_password_and_disabled_user_are_rejected_and_audited(self):
        response = self.client.post(
            "/api/auth/login/", {"username": self.user.username, "password": "wrong-password"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.client.post(
            "/api/auth/login/", {"username": self.user.username, "password": "test-password-123"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(AuditLog.objects.filter(scope="system", action="auth.login.failed", success=False).exists())

    def test_logout_invalidates_session(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post("/api/auth/logout/", {}, content_type="application/json").status_code, 200)
        self.assertIn(self.client.get("/api/organizations/current/").status_code, {401, 403})

    def test_disabled_membership_cannot_login(self):
        membership = Membership.objects.get(user=self.user, organization=self.organization)
        membership.status = "disabled"
        membership.is_active = False
        membership.save(update_fields=["status", "is_active"])
        response = self.client.post(
            "/api/auth/login/", {"username": self.user.username, "password": "test-password-123"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)
