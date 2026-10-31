from django.test import TestCase

from accounts.models import User
from features.models import Feature, FeatureRecord, FeatureVersion
from organizations.models import Permission
from organizations.services import DEFAULT_PERMISSIONS, create_organization


MANIFEST = {"version": 1, "fields": [{"key": "name", "label": "名称", "type": "text"}]}


class FeatureVersionApiTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        self.user = User.objects.create_user("version-owner", "version-password-123")
        self.organization = create_organization(user=self.user, name="版本组织")
        self.client.force_login(self.user)

    def test_publish_creates_versions_and_rollback_appends_snapshot(self):
        response = self.client.post("/api/features/", {"key": "versioned", "name": "版本功能", "manifest": MANIFEST}, content_type="application/json")
        feature_id = response.json()["id"]
        self.assertEqual(self.client.post(f"/api/features/{feature_id}/publish/", {}).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/features/{feature_id}/", {"name": "新名称"}, content_type="application/json").status_code, 200)
        self.assertEqual(self.client.post(f"/api/features/{feature_id}/publish/", {}).status_code, 200)
        versions = self.client.get(f"/api/features/{feature_id}/versions/").json()
        self.assertEqual([item["version"] for item in versions], [2, 1])
        response = self.client.post(f"/api/features/{feature_id}/rollback/", {"version": 1, "confirm": True}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        feature = Feature.objects.get(pk=feature_id)
        self.assertEqual(feature.current_version, 3)
        self.assertEqual(FeatureVersion.objects.filter(feature=feature).count(), 3)

    def test_record_read_ignores_fields_removed_by_manifest(self):
        response = self.client.post("/api/features/", {"key": "shrinking", "name": "字段功能", "manifest": {"version": 1, "fields": [{"key": "name", "label": "名称", "type": "text"}, {"key": "old", "label": "旧字段", "type": "text"}]}}, content_type="application/json")
        feature_id = response.json()["id"]
        self.client.post(f"/api/features/{feature_id}/publish/", {})
        response = self.client.post(f"/api/features/{feature_id}/records/", {"data": {"name": "记录", "old": "历史"}}, content_type="application/json")
        record_id = response.json()["id"]
        self.client.patch(f"/api/features/{feature_id}/", {"manifest": MANIFEST}, content_type="application/json")
        self.client.post(f"/api/features/{feature_id}/publish/", {})
        response = self.client.get(f"/api/features/{feature_id}/records/{record_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("old", response.json()["data"])
