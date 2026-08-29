from django.test import TestCase

from accounts.models import User
from ai.models import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_PROVIDER, LLMProviderConfig
from organizations.models import Permission
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class AiConfigApiTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        self.user = User.objects.create_user("ai-owner@example.com", "test-password-123")
        create_organization(user=self.user, name="AI Organization")
        self.client.force_login(self.user)

    def test_config_api_does_not_return_api_key(self):
        response = self.client.patch(
            "/api/ai/config/",
            {"model": "test-model", "api_key": "secret-api-key"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("api_key", response.json())
        config = LLMProviderConfig.objects.get()
        self.assertEqual(config.get_api_key(), "secret-api-key")

    def test_config_api_uses_deepseek_defaults(self):
        response = self.client.get("/api/ai/config/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["provider"], DEFAULT_PROVIDER)
        self.assertEqual(response.json()["base_url"], DEFAULT_BASE_URL)
        self.assertEqual(response.json()["model"], DEFAULT_MODEL)
