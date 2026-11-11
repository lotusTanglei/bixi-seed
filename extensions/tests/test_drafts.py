from django.test import TestCase

from accounts.models import User
from organizations.models import Permission
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class ExtensionDraftApiTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        user = User.objects.create_user("extension-owner", "test-password-123")
        create_organization(user=user, name="扩展组织")
        self.client.force_login(user)

    def test_valid_draft_is_static_checked_without_execution(self):
        response = self.client.post(
            "/api/extensions/drafts/",
            {
                "key": "customer-extension",
                "name": "客户扩展",
                "files": {"manifest.json": '{"version": 1}'},
                "dependencies": ["requests>=2"],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "validated")
        self.assertEqual(response.json()["isolation_status"], "ready")

    def test_forbidden_code_and_unsafe_path_are_rejected(self):
        response = self.client.post(
            "/api/extensions/drafts/",
            {
                "key": "unsafe-extension",
                "name": "危险扩展",
                "files": {"../run.py": "eval('x')"},
                "dependencies": [],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
