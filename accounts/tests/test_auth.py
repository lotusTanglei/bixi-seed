from django.test import TestCase

from accounts.models import User
from organizations.models import Permission
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class AuthenticationTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        self.user = User.objects.create_user(
            "login-user",
            "test-password-123",
            display_name="登录用户",
            contact="13800000001",
        )
        create_organization(user=self.user, name="Login Organization")

    def test_login_creates_session_and_returns_organizations(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "login-user", "password": "test-password-123"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["username"], "login-user")
        self.assertEqual(response.json()["user"]["email"], "")
        self.assertEqual(response.json()["user"]["contact"], "13800000001")
        self.assertEqual(len(response.json()["organizations"]), 1)
        self.assertEqual(response.json()["organizations"][0]["path"], "Login Organization")
        self.assertIsNone(response.json()["organizations"][0]["parent_id"])
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)
