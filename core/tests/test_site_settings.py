from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart

from accounts.models import User
from organizations.models import Permission
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class SiteSettingsApiTest(TestCase):
    def setUp(self):
        self.upload_directory = TemporaryDirectory()
        self.addCleanup(self.upload_directory.cleanup)
        self.settings_override = override_settings(BIXI_UPLOAD_ROOT=self.upload_directory.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        Permission.objects.bulk_create(
            [
                Permission(code=code, name=name, description=description)
                for code, name, description in DEFAULT_PERMISSIONS
            ]
        )
        self.user = User.objects.create_user(
            "settings-owner",
            "test-password-123",
            display_name="站点管理员",
            contact="settings-contact",
        )
        create_organization(user=self.user, name="设置组织")
        self.client.force_login(self.user)

    def test_site_settings_are_publicly_readable(self):
        self.client.logout()

        response = self.client.get("/api/site-settings/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["site_name"], "Bixi Seed")
        self.assertIsNone(response.json()["logo_url"])

    def test_owner_can_update_copy_and_logo(self):
        logo = SimpleUploadedFile("brand.png", b"fake-png", content_type="image/png")
        body = encode_multipart(
            BOUNDARY,
            {
                "site_name": "我的应用",
                "login_welcome": "欢迎使用我的应用",
                "login_description": "这是登录页说明",
                "home_title": "业务首页",
                "home_description": "这是首页说明",
                "logo": logo,
            },
        )

        response = self.client.patch("/api/site-settings/", body, content_type=MULTIPART_CONTENT)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["site_name"], "我的应用")
        self.assertEqual(response.json()["login_welcome"], "欢迎使用我的应用")
        self.assertIsNotNone(response.json()["logo_url"])
        logo_response = self.client.get("/api/site-settings/logo/")
        self.assertEqual(logo_response.status_code, 200)
        self.assertEqual(b"".join(logo_response.streaming_content), b"fake-png")

    def test_anonymous_user_cannot_update_site_settings(self):
        self.client.logout()

        response = self.client.patch(
            "/api/site-settings/",
            {"site_name": "不应保存"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
