import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from accounts.models import User
from ai.models import ToolCallProposal
from ai.providers import OpenAICompatibleProvider
from features.models import Feature, FeatureRecord
from organizations.models import Membership, Permission, Role
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class ModelToolPlanApiTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create([
            Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS
        ])
        self.user = User.objects.create_user("tool-planner", "test-password-123")
        self.organization = create_organization(user=self.user, name="模型工具规划")
        self.client.force_login(self.user)
        self.feature = Feature.objects.create(
            organization=self.organization, key="model-tools", name="客户", status="published", created_by=self.user,
            manifest={"version": 1, "fields": [{"key": "name", "label": "名称", "type": "text"}]},
        )

    def plan(self, client=None):
        return (client or self.client).post("/api/ai/tool-plan/", {
            "feature_id": str(self.feature.pk), "requirement": "创建名为新客户的记录",
        }, content_type="application/json")

    def output(self, **changes):
        result = {"name": "feature_record_create", "arguments": {"feature_id": str(self.feature.pk), "data": {"name": "新客户"}}}
        result.update(changes)
        return result

    @patch("ai.views.get_provider")
    def test_model_call_creates_only_a_preview_with_fixed_tools_and_no_record_data(self, provider_factory):
        FeatureRecord.objects.create(feature=self.feature, data={"name": "private-record-value"}, created_by=self.user, updated_by=self.user)
        provider = provider_factory.return_value
        provider.complete_tool_call.return_value = self.output()
        response = self.plan()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "proposed")
        self.assertEqual(response.json()["tool"], "feature.record.create")
        self.assertEqual(FeatureRecord.objects.count(), 1)
        provider_factory.assert_called_once_with(self.organization)
        messages, tools = provider.complete_tool_call.call_args.args
        self.assertEqual({item["function"]["name"] for item in tools}, {"feature_record_create", "feature_record_update", "feature_record_delete"})
        self.assertIn(str(self.feature.pk), messages[0]["content"])
        self.assertNotIn("private-record-value", json.dumps(messages))
        self.assertTrue(self.organization.audit_logs.filter(action="ai.tool.planned").exists())

    @patch("ai.views.get_provider")
    def test_unknown_tool_wrong_feature_and_malformed_arguments_are_rejected(self, provider_factory):
        other = Feature.objects.create(organization=self.organization, key="wrong-tool-feature", name="其他", status="published", manifest=self.feature.manifest, created_by=self.user)
        for output in (
            self.output(name="shell_exec"), self.output(name="feature.record.create"),
            self.output(arguments=[]), self.output(arguments={"feature_id": str(self.feature.pk), "data": {}, "code": "forbidden"}),
            self.output(arguments={"feature_id": str(other.pk), "data": {"name": "wrong"}}),
        ):
            with self.subTest(output=output):
                provider_factory.return_value.complete_tool_call.return_value = output
                self.assertEqual(self.plan().status_code, 422)
        self.assertFalse(ToolCallProposal.objects.exists())
        self.assertEqual(self.organization.audit_logs.filter(action="ai.tool.plan_failed", success=False).count(), 5)

    def test_missing_organization_model_configuration_is_explicit(self):
        self.assertEqual(self.plan().status_code, 422)
        self.assertFalse(ToolCallProposal.objects.exists())
        self.assertTrue(self.organization.audit_logs.filter(action="ai.tool.plan_failed", success=False).exists())

    @patch("ai.views.get_provider")
    def test_permission_and_foreign_feature_fail_before_a_model_call(self, provider_factory):
        user = User.objects.create_user("model-reader", "test-password-123")
        role = Role.objects.create(organization=self.organization, code="model-reader", name="只读规划")
        role.permissions.add(Permission.objects.get(code="ai.use"))
        Membership.objects.create(organization=self.organization, user=user, role=role)
        client = self.client.__class__()
        client.force_login(user)
        self.assertEqual(self.plan(client).status_code, 403)
        role.permissions.add(Permission.objects.get(code="feature.create"))
        role.permissions.remove(Permission.objects.get(code="ai.use"))
        self.assertEqual(self.plan(client).status_code, 403)
        foreign_user = User.objects.create_user("foreign-planner", "test-password-123")
        create_organization(user=foreign_user, name="外组织")
        foreign = self.client.__class__()
        foreign.force_login(foreign_user)
        self.assertEqual(self.plan(foreign).status_code, 404)
        provider_factory.assert_not_called()

    @patch("ai.views.get_provider")
    def test_model_allowed_tools_and_returned_arguments_use_current_permissions(self, provider_factory):
        user = User.objects.create_user("model-creator", "test-password-123")
        role = Role.objects.create(organization=self.organization, code="model-creator", name="新增")
        role.permissions.add(*Permission.objects.filter(code__in=["ai.use", "feature.create"]))
        Membership.objects.create(organization=self.organization, user=user, role=role)
        client = self.client.__class__()
        client.force_login(user)
        def plan_and_revoke(messages, tools):
            self.assertEqual([item["function"]["name"] for item in tools], ["feature_record_create"])
            role.permissions.remove(Permission.objects.get(code="feature.create"))
            return self.output()
        provider_factory.return_value.complete_tool_call.side_effect = plan_and_revoke
        self.assertEqual(self.plan(client).status_code, 422)
        self.assertFalse(ToolCallProposal.objects.exists())

    @patch("ai.views.get_provider")
    def test_ai_permission_or_membership_revoked_during_model_request_is_rejected(self, provider_factory):
        for revoke_membership in (False, True):
            with self.subTest(revoke_membership=revoke_membership):
                user = User.objects.create_user(f"revoked-planner-{revoke_membership}", "test-password-123")
                role = Role.objects.create(organization=self.organization, code=f"revoked-planner-{revoke_membership}", name="待撤权")
                role.permissions.add(*Permission.objects.filter(code__in=["ai.use", "feature.create"]))
                membership = Membership.objects.create(organization=self.organization, user=user, role=role)
                client = self.client.__class__()
                client.force_login(user)
                def revoke_access(messages, tools):
                    if revoke_membership:
                        membership.delete()
                    else:
                        role.permissions.remove(Permission.objects.get(code="ai.use"))
                    return self.output()
                provider_factory.return_value.complete_tool_call.side_effect = revoke_access
                self.assertEqual(self.plan(client).status_code, 403)
        self.assertFalse(ToolCallProposal.objects.exists())


class OpenAIToolCallParsingTest(TestCase):
    def provider(self, calls):
        provider = object.__new__(OpenAICompatibleProvider)
        provider.config = SimpleNamespace(model="fixed-test-model")
        create = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=calls))]))
        provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        return provider, create

    def call(self, arguments='{"feature_id": "uuid", "data": {}}', name="feature_record_create"):
        return SimpleNamespace(type="function", function=SimpleNamespace(name=name, arguments=arguments))

    def test_provider_sends_single_fixed_tool_call_request(self):
        provider, create = self.provider([self.call()])
        tools = [{"type": "function", "function": {"name": "feature_record_create"}}]
        result = provider.complete_tool_call([{"role": "user", "content": "需求"}], tools)
        self.assertEqual(result["name"], "feature_record_create")
        self.assertEqual(create.call_args.kwargs["tools"], tools)
        self.assertFalse(create.call_args.kwargs["parallel_tool_calls"])
        self.assertEqual(create.call_args.kwargs["tool_choice"], "required")
        self.assertEqual(create.call_count, 1)

    def test_zero_multiple_and_invalid_json_tool_calls_are_rejected_without_retry(self):
        for calls in ([], [self.call(), self.call()], [self.call(arguments="not-json")]):
            with self.subTest(calls=calls):
                provider, create = self.provider(calls)
                with self.assertRaises(ValueError):
                    provider.complete_tool_call([], [])
                self.assertEqual(create.call_count, 1)
