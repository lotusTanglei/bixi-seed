from django.test import TestCase

from accounts.models import User
from features.models import Feature, FeatureRecord
from organizations.models import Permission
from organizations.services import DEFAULT_PERMISSIONS, create_organization


MANIFEST = {
    "version": 1,
    "fields": [
        {"key": "name", "label": "名称", "type": "text", "required": True, "max_length": 80},
        {"key": "amount", "label": "金额", "type": "number", "min": 0},
        {"key": "stage", "label": "阶段", "type": "enum", "options": ["新建", "成交"]},
        {"key": "enabled", "label": "启用", "type": "boolean"},
        {"key": "follow_up", "label": "跟进日期", "type": "date"},
    ],
    "list": {"columns": ["name", "amount", "stage"], "search_fields": ["name", "stage"]},
}


class FeatureApiTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [
                Permission(code=code, name=name, description=description)
                for code, name, description in DEFAULT_PERMISSIONS
            ]
        )
        self.user = User.objects.create_user("feature-owner@example.com", "test-password-123")
        self.organization = create_organization(user=self.user, name="功能组织")
        self.client.force_login(self.user)

    def create_and_publish(self):
        response = self.client.post(
            "/api/features/",
            {"key": "sales-lead", "name": "销售线索", "manifest": MANIFEST},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        feature_id = response.json()["id"]
        self.assertEqual(response.json()["status"], "draft")
        response = self.client.post(f"/api/features/{feature_id}/publish/", {}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        return feature_id

    def test_manifest_publish_and_record_crud(self):
        feature_id = self.create_and_publish()
        response = self.client.get("/api/features/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["key"], "sales-lead")

        response = self.client.post(
            f"/api/features/{feature_id}/records/",
            {"data": {"name": "客户 A", "amount": 120, "stage": "新建", "enabled": True, "follow_up": "2026-08-27"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        record_id = response.json()["id"]
        response = self.client.get(f"/api/features/{feature_id}/records/?q=客户")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pagination"]["total"], 1)
        self.assertEqual(self.client.get(f"/api/features/{feature_id}/records/{record_id}/").status_code, 200)
        response = self.client.patch(
            f"/api/features/{feature_id}/records/{record_id}/",
            {"data": {"stage": "成交"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["stage"], "成交")
        self.assertEqual(self.client.delete(f"/api/features/{feature_id}/records/{record_id}/").status_code, 204)
        self.assertFalse(FeatureRecord.objects.exists())

    def test_invalid_manifest_and_invalid_record_are_rejected(self):
        response = self.client.post(
            "/api/features/",
            {"key": "bad-feature", "name": "错误功能", "manifest": {"fields": [{"key": "x", "type": "code"}]}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/api/features/",
            {"key": "bad-permission", "name": "错误权限", "manifest": {"fields": [{"key": "name", "label": "名称", "type": "text"}], "permissions": {"read": []}}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        feature_id = self.create_and_publish()
        response = self.client.post(
            f"/api/features/{feature_id}/records/",
            {"data": {"name": "", "amount": -1, "stage": "未知", "enabled": "yes", "follow_up": "tomorrow"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_normal_member_can_read_but_cannot_write_records(self):
        feature_id = self.create_and_publish()
        member = User.objects.create_user("feature-member@example.com", "test-password-123")
        member_role = self.organization.roles.get(code="member")
        from organizations.models import Membership

        Membership.objects.create(organization=self.organization, user=member, role=member_role)
        ordinary_client = self.client.__class__()
        ordinary_client.force_login(member)
        self.assertEqual(ordinary_client.get(f"/api/features/{feature_id}/records/").status_code, 200)
        self.assertEqual(
            ordinary_client.post(
                f"/api/features/{feature_id}/records/",
                {"data": {"name": "不允许", "stage": "新建"}},
                content_type="application/json",
            ).status_code,
            403,
        )

    def test_manifest_can_disable_an_action(self):
        manifest = {**MANIFEST, "actions": {"create": False}}
        response = self.client.post(
            "/api/features/",
            {"key": "read-only", "name": "只读功能", "manifest": manifest},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        feature_id = response.json()["id"]
        self.assertEqual(self.client.post(f"/api/features/{feature_id}/publish/", {}).status_code, 200)
        response = self.client.post(
            f"/api/features/{feature_id}/records/",
            {"data": {"name": "不允许", "stage": "新建"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_manifest_can_disable_update_and_delete(self):
        manifest = {**MANIFEST, "actions": {"update": False, "delete": False}}
        response = self.client.post(
            "/api/features/",
            {"key": "protected-records", "name": "受保护数据", "manifest": manifest},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        feature_id = response.json()["id"]
        self.assertEqual(self.client.post(f"/api/features/{feature_id}/publish/", {}).status_code, 200)
        response = self.client.post(
            f"/api/features/{feature_id}/records/",
            {"data": {"name": "保留数据", "stage": "新建"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        record_id = response.json()["id"]
        self.assertEqual(
            self.client.patch(
                f"/api/features/{feature_id}/records/{record_id}/",
                {"data": {"stage": "成交"}},
                content_type="application/json",
            ).status_code,
            403,
        )
        self.assertEqual(self.client.delete(f"/api/features/{feature_id}/records/{record_id}/").status_code, 403)

    def test_records_can_be_sorted_by_numeric_field(self):
        feature_id = self.create_and_publish()
        for name, amount in (("一", 100), ("二", 20)):
            response = self.client.post(
                f"/api/features/{feature_id}/records/",
                {"data": {"name": name, "amount": amount, "stage": "新建"}},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 201)
        response = self.client.get(f"/api/features/{feature_id}/records/?sort=amount")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["data"]["amount"] for item in response.json()["items"]], [20, 100])

    def test_corrupt_published_feature_is_hidden_from_public_list(self):
        Feature.objects.create(
            organization=self.organization,
            key="corrupt-feature",
            name="损坏功能",
            status="published",
            manifest={"fields": [{"key": "name", "type": ["invalid"]}]},
            created_by=self.user,
        )
        response = self.client.get("/api/features/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_feature_direct_access_is_scoped_to_the_organization(self):
        other_user = User.objects.create_user("other-feature@example.com", "test-password-123")
        other_organization = create_organization(user=other_user, name="其他功能组织")
        other_feature = Feature.objects.create(
            organization=other_organization,
            key="private-feature",
            name="其他功能",
            status="published",
            manifest=MANIFEST,
            created_by=other_user,
        )
        self.assertEqual(self.client.get(f"/api/features/{other_feature.id}/").status_code, 404)
