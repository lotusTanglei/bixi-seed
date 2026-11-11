from django.test import TestCase

from accounts.models import User
from features.models import Feature, FeatureRecord
from organizations.models import Membership, Permission, Role
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class RoleExtensionsApiTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        self.owner = User.objects.create_user("role-owner", "test-password-123")
        self.organization = create_organization(user=self.owner, name="角色扩展组织")
        self.client.force_login(self.owner)

    def test_copy_preserves_permissions_and_scope(self):
        source = Role.objects.create(
            organization=self.organization,
            code="sales",
            name="销售",
            data_scope={"mode": "own"},
        )
        source.permissions.add(Permission.objects.get(code="feature.read"))
        response = self.client.post(
            f"/api/organizations/roles/{source.pk}/copy/",
            {"code": "sales-copy", "name": "销售副本"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        copied = Role.objects.get(code="sales-copy")
        self.assertEqual(copied.data_scope, {"mode": "own"})
        self.assertEqual(list(copied.permissions.values_list("code", flat=True)), ["feature.read"])

    def test_batch_role_assignment_is_atomic_and_audited(self):
        role = Role.objects.create(organization=self.organization, code="limited", name="受限")
        members = []
        for index in range(2):
            user = User.objects.create_user(f"batch-{index}", "test-password-123")
            members.append(Membership.objects.create(organization=self.organization, user=user, role=role))
        response = self.client.post(
            "/api/organizations/members/batch-role/",
            {"user_ids": [item.user_id for item in members], "role_id": role.id},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["updated"]), 2)
        self.assertTrue(self.organization.audit_logs.filter(action="member.roles.batch_updated").exists())

    def test_own_scope_hides_other_members_records(self):
        role = Role.objects.create(
            organization=self.organization,
            code="own-data",
            name="个人数据",
            data_scope={"mode": "own"},
        )
        role.permissions.add(*Permission.objects.filter(code__in=["feature.read", "feature.create"]))
        user = User.objects.create_user("own-data", "test-password-123")
        membership = Membership.objects.create(organization=self.organization, user=user, role=role)
        feature = Feature.objects.create(
            organization=self.organization,
            key="own-scope",
            name="个人范围",
            status="published",
            manifest={"version": 1, "fields": [{"key": "name", "label": "名称", "type": "text"}]},
            created_by=self.owner,
        )
        FeatureRecord.objects.create(feature=feature, data={"name": "owner"}, created_by=self.owner, updated_by=self.owner)
        FeatureRecord.objects.create(feature=feature, data={"name": "member"}, created_by=user, updated_by=user)
        member_client = self.client.__class__()
        member_client.force_login(user)
        response = member_client.get(f"/api/features/{feature.pk}/records/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["data"]["name"] for item in response.json()["items"]], ["member"])
