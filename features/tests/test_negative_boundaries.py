from django.test import TestCase

from accounts.models import User
from features.models import Feature
from organizations.models import Permission
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class FeatureNegativeBoundaryTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        self.user = User.objects.create_user("feature-boundary", "boundary-password-123")
        create_organization(user=self.user, name="功能边界组织")
        self.client.force_login(self.user)

    def test_manifest_rejects_invalid_bounds_and_duplicate_keys(self):
        manifest = {
            "version": 1,
            "fields": [
                {"key": "amount", "label": "金额", "type": "number", "min": 10, "max": 1},
                {"key": "amount", "label": "重复", "type": "text"},
            ],
        }
        response = self.client.post(
            "/api/features/", {"key": "invalid-bounds", "name": "非法定义", "manifest": manifest}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_feature_key_and_overlong_name_are_rejected(self):
        manifest = {"version": 1, "fields": [{"key": "name", "label": "名称", "type": "text"}]}
        self.assertEqual(self.client.post("/api/features/", {"key": "duplicate", "name": "重复", "manifest": manifest}, content_type="application/json").status_code, 201)
        self.assertEqual(self.client.post("/api/features/", {"key": "duplicate", "name": "重复", "manifest": manifest}, content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/api/features/", {"key": "long-name", "name": "x" * 161, "manifest": manifest}, content_type="application/json").status_code, 400)

    def test_disabled_feature_records_are_not_accessible(self):
        manifest = {"version": 1, "fields": [{"key": "name", "label": "名称", "type": "text"}]}
        response = self.client.post("/api/features/", {"key": "disabled", "name": "停用", "manifest": manifest}, content_type="application/json")
        feature_id = response.json()["id"]
        self.client.post(f"/api/features/{feature_id}/publish/", {})
        self.client.post(f"/api/features/{feature_id}/disable/", {})
        self.assertEqual(self.client.get(f"/api/features/{feature_id}/records/").status_code, 404)
