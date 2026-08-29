import json
from unittest.mock import patch

from django.test import TestCase

from accounts.models import User
from ai.models import FeatureProposal
from features.models import Feature
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
        user = User.objects.create_user("planner@example.com", "test-password-123")
        create_organization(user=user, name="AI 组织")
        self.client.force_login(user)

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
