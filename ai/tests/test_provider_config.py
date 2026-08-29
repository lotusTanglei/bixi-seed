from django.test import TestCase

from accounts.models import User
from ai.models import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_PROVIDER, LLMProviderConfig
from organizations.models import Permission
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class ProviderConfigTest(TestCase):
    def test_new_config_defaults_to_deepseek(self):
        user = User.objects.create_user("owner@example.com", "test-password-123")
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        organization = create_organization(user=user, name="AI Test")

        config = LLMProviderConfig.objects.create(organization=organization)

        self.assertEqual(config.provider, DEFAULT_PROVIDER)
        self.assertEqual(config.base_url, DEFAULT_BASE_URL)
        self.assertEqual(config.model, DEFAULT_MODEL)

    def test_api_key_is_not_stored_as_plaintext(self):
        user = User.objects.create_user("owner@example.com", "test-password-123")
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        organization = create_organization(user=user, name="AI Test")
        config = LLMProviderConfig.objects.create(organization=organization)
        config.set_api_key("secret-api-key")
        config.save()

        config.refresh_from_db()
        self.assertNotEqual(config.api_key_encrypted, "secret-api-key")
        self.assertEqual(config.get_api_key(), "secret-api-key")
