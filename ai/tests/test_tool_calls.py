import json
from unittest.mock import patch

from django.test import TestCase

from accounts.models import User
from ai.models import ToolCallProposal
from features.models import Feature, FeatureRecord
from organizations.models import Membership, Permission, Role
from organizations.services import DEFAULT_PERMISSIONS, create_organization, write_audit


class ControlledToolApiTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create([
            Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS
        ])
        self.user = User.objects.create_user("tool-owner", "test-password-123")
        self.organization = create_organization(user=self.user, name="工具验收")
        self.client.force_login(self.user)
        self.feature = Feature.objects.create(
            organization=self.organization, key="tool-records", name="记录", status="published", created_by=self.user,
            manifest={"version": 1, "fields": [{"key": "name", "label": "名称", "type": "text"}]},
        )

    def propose(self, action="create", *, record=None, data=None, client=None):
        arguments = {"feature_id": str(self.feature.pk)}
        if record:
            arguments["record_id"] = record.pk
        if action != "delete":
            arguments["data"] = {"name": "after"} if data is None else data
        return (client or self.client).post("/api/ai/tool-proposals/", {
            "tool": f"feature.record.{action}", "arguments": arguments,
        }, content_type="application/json")

    def confirm(self, proposal_id, *, client=None):
        return (client or self.client).post(f"/api/ai/tool-proposals/{proposal_id}/confirm/", {"confirm": True}, content_type="application/json")

    def revoke(self, proposal_id, *, client=None):
        return (client or self.client).post(f"/api/ai/tool-proposals/{proposal_id}/revoke/", {"confirm": True}, content_type="application/json")

    def record(self, **kwargs):
        return FeatureRecord.objects.create(feature=self.feature, data={"name": "before"}, created_by=kwargs.get("user", self.user), updated_by=self.user)

    def test_catalog_has_typed_parameters_risk_and_record_only_tools(self):
        catalog = self.client.get("/api/ai/tools/").json()
        self.assertEqual({item["name"] for item in catalog}, {f"feature.record.{action}" for action in ("create", "update", "delete")})
        self.assertEqual({item["risk"] for item in catalog}, {"medium", "high"})
        self.assertEqual(catalog[0]["arguments"]["properties"]["feature_id"]["format"], "uuid")
        self.assertFalse(catalog[0]["arguments"]["additionalProperties"])

    def test_malformed_and_extra_parameters_are_rejected_and_audited(self):
        for arguments in (
            {"feature_id": "bad-uuid", "record_id": 1, "data": {}},
            {"feature_id": str(self.feature.pk), "record_id": 1, "data": {}, "shell": "ignored"},
            {"feature_id": str(self.feature.pk), "record_id": 1, "data": []},
            {"feature_id": str(self.feature.pk), "record_id": True, "data": {}},
        ):
            response = self.client.post("/api/ai/tool-proposals/", {
                "tool": "feature.record.update", "arguments": arguments,
            }, content_type="application/json")
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.organization.audit_logs.filter(action="ai.tool.rejected", success=False).count(), 4)
        self.assertFalse(ToolCallProposal.objects.exists())

    def test_feature_action_switch_is_enforced_at_proposal_and_confirmation(self):
        for action in ("create", "update", "delete"):
            record = self.record()
            proposal = self.propose(action, record=record if action != "create" else None).json()
            self.feature.manifest["actions"] = {action: False}
            self.feature.save(update_fields=["manifest"])
            self.assertEqual(self.propose(action, record=record if action != "create" else None).status_code, 400)
            self.assertEqual(self.confirm(proposal["id"]).status_code, 409)
            record.refresh_from_db()
            self.assertEqual(record.data, {"name": "before"})
            del self.feature.manifest["actions"]
            self.feature.save(update_fields=["manifest"])

    def test_preview_contains_field_permission_and_data_diff(self):
        record = self.record()
        payload = self.propose("update", record=record).json()
        self.assertEqual(payload["risk"], "high")
        self.assertEqual(payload["preview"]["before"], {"name": "before"})
        self.assertEqual(payload["diff"]["data"]["changed"]["name"], {"before": "before", "after": "after"})
        self.assertEqual(payload["diff"]["fields"]["before"], self.feature.manifest["fields"])
        self.assertEqual(payload["diff"]["permissions"]["before"]["required"], "feature.update")
        self.assertEqual(payload["diff"]["permissions"]["before"], payload["diff"]["permissions"]["after"])

    def test_changed_record_or_schema_invalidates_confirmation(self):
        record = self.record()
        proposal_id = self.propose("update", record=record).json()["id"]
        record.data = {"name": "concurrent"}
        record.save()
        self.assertEqual(self.confirm(proposal_id).status_code, 409)
        self.assertEqual(FeatureRecord.objects.get(pk=record.pk).data, {"name": "concurrent"})
        proposal_id = self.propose("update", record=record).json()["id"]
        self.feature.manifest["fields"][0]["label"] = "新标签"
        self.feature.save()
        self.assertEqual(self.confirm(proposal_id).status_code, 409)
        self.assertEqual(self.organization.audit_logs.filter(action="ai.tool.failed", success=False).count(), 2)

    def test_confirm_and_revoke_require_explicit_confirmation_and_are_one_time(self):
        proposal_id = self.propose().json()["id"]
        self.assertEqual(self.client.post(f"/api/ai/tool-proposals/{proposal_id}/confirm/", {}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/ai/tool-proposals/{proposal_id}/revoke/", {}).status_code, 400)
        self.assertFalse(FeatureRecord.objects.exists())
        self.assertEqual(self.revoke(proposal_id).status_code, 200)
        self.assertEqual(self.confirm(proposal_id).status_code, 400)
        self.assertEqual(self.revoke(proposal_id).status_code, 400)

    def test_confirmed_create_update_delete_can_be_reverted(self):
        create_id = self.propose().json()["id"]
        result = self.confirm(create_id)
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("undo", result.json()["result"])
        record = FeatureRecord.objects.get()
        update_id = self.propose("update", record=record, data={"name": "edited"}).json()["id"]
        self.assertEqual(self.confirm(update_id).status_code, 200)
        self.assertEqual(self.revoke(update_id).status_code, 200)
        record.refresh_from_db()
        self.assertEqual(record.data, {"name": "after"})
        delete_id = self.propose("delete", record=record).json()["id"]
        self.assertEqual(self.confirm(delete_id).status_code, 200)
        self.assertFalse(FeatureRecord.objects.exists())
        self.assertEqual(self.revoke(delete_id).status_code, 200)
        restored = FeatureRecord.objects.get(pk=record.pk)
        self.assertEqual(restored.data, {"name": "after"})
        self.assertEqual(restored.created_by_id, self.user.pk)
        # Undoing later work changes the revision; an older create cannot erase it.
        self.assertEqual(self.revoke(create_id).status_code, 409)
        new_create_id = self.propose(data={"name": "disposable"}).json()["id"]
        self.assertEqual(self.confirm(new_create_id).status_code, 200)
        self.assertEqual(self.revoke(new_create_id).status_code, 200)
        self.assertEqual(FeatureRecord.objects.count(), 1)
        self.assertEqual(self.organization.audit_logs.filter(action="ai.tool.reverted").count(), 3)

    def test_revert_refuses_concurrent_writes_or_disabled_inverse_action(self):
        record = self.record()
        proposal_id = self.propose("update", record=record).json()["id"]
        self.assertEqual(self.confirm(proposal_id).status_code, 200)
        record.refresh_from_db()
        record.data = {"name": "later"}
        record.save()
        self.assertEqual(self.revoke(proposal_id).status_code, 409)
        self.assertEqual(FeatureRecord.objects.get(pk=record.pk).data, {"name": "later"})
        proposal_id = self.propose().json()["id"]
        self.assertEqual(self.confirm(proposal_id).status_code, 200)
        self.feature.manifest["actions"] = {"delete": False}
        self.feature.save()
        self.assertEqual(self.revoke(proposal_id).status_code, 409)

    def test_current_permissions_scope_and_organization_are_rechecked(self):
        role = Role.objects.create(organization=self.organization, code="tool-member", name="成员")
        role.permissions.set(Permission.objects.filter(code__in=["ai.use", "feature.create", "feature.update", "feature.delete"]))
        user = User.objects.create_user("tool-member", "test-password-123")
        Membership.objects.create(organization=self.organization, user=user, role=role)
        client = self.client.__class__()
        client.force_login(user)
        proposal_id = self.propose(client=client).json()["id"]
        role.permissions.remove(Permission.objects.get(code="feature.create"))
        self.assertEqual(self.confirm(proposal_id, client=client).status_code, 409)
        self.assertFalse(FeatureRecord.objects.exists())
        role.permissions.add(Permission.objects.get(code="feature.create"))
        record = self.record()
        proposal_id = self.propose("delete", record=record, client=client).json()["id"]
        self.assertEqual(self.confirm(proposal_id, client=client).status_code, 200)
        role.permissions.remove(Permission.objects.get(code="feature.create"))
        self.assertEqual(self.revoke(proposal_id, client=client).status_code, 409)
        role.permissions.add(Permission.objects.get(code="feature.create"))
        role.data_scope = {"mode": "own"}
        role.save()
        self.assertEqual(self.revoke(proposal_id, client=client).status_code, 409)
        self.assertFalse(FeatureRecord.objects.exists())
        self.assertEqual(self.propose("update", record=record, client=client).status_code, 400)
        foreign_user = User.objects.create_user("foreign-tool", "test-password-123")
        create_organization(user=foreign_user, name="外组织")
        foreign = self.client.__class__()
        foreign.force_login(foreign_user)
        self.assertEqual(self.confirm(proposal_id, client=foreign).status_code, 404)
        self.assertEqual(foreign.get(f"/api/ai/tool-proposals/{proposal_id}/").status_code, 404)

    def test_execution_exception_rolls_back_data_and_success_audit_but_keeps_failure_audit(self):
        for fail_action in ("feature.record.created", "ai.tool.confirmed"):
            with self.subTest(fail_action=fail_action):
                proposal_id = self.propose(data={"name": "sensitive-value"}).json()["id"]
                def fail_audit(**kwargs):
                    if kwargs["action"] == fail_action:
                        raise RuntimeError("audit unavailable")
                    return write_audit(**kwargs)
                with patch("ai.views.write_audit", side_effect=fail_audit):
                    response = self.confirm(proposal_id)
                self.assertEqual(response.status_code, 500)
                self.assertFalse(FeatureRecord.objects.exists())
                self.assertEqual(ToolCallProposal.objects.get(pk=proposal_id).status, "failed")
        self.assertFalse(self.organization.audit_logs.filter(action="ai.tool.confirmed").exists())
        self.assertFalse(self.organization.audit_logs.filter(action="feature.record.created").exists())
        self.assertEqual(self.organization.audit_logs.filter(action="ai.tool.failed", success=False).count(), 2)
        self.assertNotIn("sensitive-value", json.dumps(list(self.organization.audit_logs.values_list("metadata", flat=True))))

    def test_proposal_read_rechecks_owner_permissions_and_data_scope(self):
        role = Role.objects.create(organization=self.organization, code="reader-manager", name="个人管理员", data_scope={"mode": "own"})
        role.permissions.set(Permission.objects.filter(code__in=["ai.use", "feature.manage", "feature.update"]))
        user = User.objects.create_user("reader-manager", "test-password-123")
        Membership.objects.create(organization=self.organization, user=user, role=role)
        client = self.client.__class__()
        client.force_login(user)
        record = self.record()
        owner_proposal = self.propose("update", record=record).json()["id"]
        self.assertEqual(client.get(f"/api/ai/tool-proposals/{owner_proposal}/").status_code, 404)
        role.data_scope = {"mode": "all"}
        role.save()
        proposal_id = self.propose("update", record=record, client=client).json()["id"]
        self.assertEqual(client.get(f"/api/ai/tool-proposals/{proposal_id}/").status_code, 200)
        role.data_scope = {"mode": "own"}
        role.save()
        self.assertEqual(client.get(f"/api/ai/tool-proposals/{proposal_id}/").status_code, 404)
        role.data_scope = {"mode": "all"}
        role.save()
        role.permissions.remove(Permission.objects.get(code="feature.update"))
        self.assertEqual(client.get(f"/api/ai/tool-proposals/{proposal_id}/").status_code, 404)
        response = self.revoke(proposal_id, client=client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["preview"], {})
        self.assertEqual(response.json()["result"], {})

    def test_revert_exception_rolls_back_compensation_and_keeps_failure_audit(self):
        for fail_action in ("feature.record.reverted", "ai.tool.reverted"):
            with self.subTest(fail_action=fail_action):
                record = self.record()
                proposal_id = self.propose("update", record=record).json()["id"]
                self.assertEqual(self.confirm(proposal_id).status_code, 200)
                def fail_audit(**kwargs):
                    if kwargs["action"] == fail_action:
                        raise RuntimeError("audit unavailable")
                    return write_audit(**kwargs)
                with patch("ai.views.write_audit", side_effect=fail_audit):
                    response = self.revoke(proposal_id)
                self.assertEqual(response.status_code, 500)
                self.assertEqual(FeatureRecord.objects.get(pk=record.pk).data, {"name": "after"})
                self.assertEqual(ToolCallProposal.objects.get(pk=proposal_id).status, "confirmed")
        self.assertFalse(self.organization.audit_logs.filter(action__in=["feature.record.reverted", "ai.tool.reverted"]).exists())
        self.assertEqual(self.organization.audit_logs.filter(action="ai.tool.revert_failed", success=False).count(), 2)
