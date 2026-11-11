import json
from unittest.mock import patch

from django.test import TestCase

from accounts.models import User
from ai.models import FeatureProposal
from features.models import Feature
from features.models import FeatureRecord
from organizations.models import Permission
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class FakeProvider:
    def complete_json(self, messages):
        return json.dumps(
            {
                "key": "customer-list",
                "name": "客户管理",
                "description": "管理客户信息",
                "manifest": {
                    "version": 1,
                    "fields": [{"key": "name", "label": "客户名称", "type": "text", "required": True}],
                },
            }
        )


class FeaturePlanningApiTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [
                Permission(code=code, name=name, description=description)
                for code, name, description in DEFAULT_PERMISSIONS
            ]
        )
        self.user = User.objects.create_user("planner@example.com", "test-password-123")
        create_organization(user=self.user, name="AI 组织")
        self.client.force_login(self.user)

    @patch("ai.views.get_provider", return_value=FakeProvider())
    def test_plan_requires_confirmation_and_publish(self, provider):
        response = self.client.post(
            "/api/ai/feature-plan/",
            {"requirement": "创建一个客户管理，包含客户名称"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        proposal_id = response.json()["id"]
        proposal = FeatureProposal.objects.get(pk=proposal_id)
        self.assertEqual(proposal.status, "proposed")
        self.assertFalse(Feature.objects.exists())

        response = self.client.post(
            f"/api/ai/feature-proposals/{proposal_id}/confirm/", {}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        feature_id = response.json()["feature"]["id"]
        self.assertEqual(Feature.objects.get(pk=feature_id).status, "draft")

        response = self.client.post(f"/api/features/{feature_id}/publish/", {}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Feature.objects.get(pk=feature_id).status, "published")
        self.assertEqual(
            self.client.post(f"/api/ai/feature-proposals/{proposal_id}/confirm/", {}, content_type="application/json").status_code,
            400,
        )

    @patch("ai.views.get_provider", return_value=FakeProvider())
    def test_reject_is_one_time_operation(self, provider):
        response = self.client.post(
            "/api/ai/feature-plan/", {"requirement": "创建一个客户管理"}, content_type="application/json"
        )
        proposal_id = response.json()["id"]
        self.assertEqual(self.client.post(f"/api/ai/feature-proposals/{proposal_id}/reject/", {}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/ai/feature-proposals/{proposal_id}/reject/", {}).status_code, 400)

    def test_tool_proposal_requires_confirmation_and_writes_audit(self):
        feature = Feature.objects.create(
            organization=self.user.memberships.first().organization,
            key="tool-feature",
            name="工具功能",
            status="published",
            manifest={"version": 1, "fields": [{"key": "name", "label": "名称", "type": "text"}]},
            created_by=self.user,
        )
        response = self.client.get("/api/ai/tools/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("feature.record.create", [item["name"] for item in response.json()])
        response = self.client.post(
            "/api/ai/tool-proposals/",
            {"tool": "feature.record.create", "arguments": {"feature_id": str(feature.pk), "data": {"name": "客户"}}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        proposal_id = response.json()["id"]
        self.assertFalse(FeatureRecord.objects.exists())
        self.assertEqual(self.client.post(f"/api/ai/tool-proposals/{proposal_id}/revoke/", {}).status_code, 200)
        self.assertFalse(FeatureRecord.objects.exists())

    def test_confirmed_tool_creates_record_after_preview(self):
        feature = Feature.objects.create(
            organization=self.user.memberships.first().organization,
            key="tool-confirm",
            name="工具确认",
            status="published",
            manifest={"version": 1, "fields": [{"key": "name", "label": "名称", "type": "text"}]},
            created_by=self.user,
        )
        response = self.client.post(
            "/api/ai/tool-proposals/",
            {"tool": "feature.record.create", "arguments": {"feature_id": str(feature.pk), "data": {"name": "确认"}}},
            content_type="application/json",
        )
        proposal_id = response.json()["id"]
        response = self.client.post(
            f"/api/ai/tool-proposals/{proposal_id}/confirm/",
            {"confirm": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "confirmed")
        self.assertEqual(FeatureRecord.objects.get().data["name"], "确认")
        self.assertTrue(
            self.user.memberships.first().organization.audit_logs.filter(action="ai.tool.confirmed").exists()
        )
