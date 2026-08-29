from django.test import TestCase

from accounts.models import User
from organizations.models import AuditLog, Membership, Permission, Role
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class OrganizationManagementApiTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [
                Permission(code=code, name=name, description=description)
                for code, name, description in DEFAULT_PERMISSIONS
            ]
        )
        self.owner = User.objects.create_user("owner-management@example.com", "test-password-123")
        self.organization = create_organization(user=self.owner, name="管理组织")
        self.client.force_login(self.owner)

    def test_default_roles_include_owner_admin_and_member(self):
        self.assertEqual(
            set(Role.objects.filter(organization=self.organization).values_list("code", flat=True)),
            {"owner", "admin", "member"},
        )

        response = self.client.get("/api/organizations/roles/")
        self.assertEqual(response.status_code, 200)
        roles = {item["code"]: item for item in response.json()}
        self.assertEqual(roles["owner"]["member_count"], 1)
        self.assertEqual(roles["admin"]["member_count"], 0)
        self.assertTrue(roles["owner"]["permissions"])

    def test_owner_can_add_disable_restore_and_remove_member(self):
        member_role = Role.objects.get(organization=self.organization, code="member")
        response = self.client.post(
            "/api/organizations/members/",
            {
                "username": "member01",
                "display_name": "普通成员",
                "contact": "13800000000",
                "password": "member-password-123",
                "role_id": member_role.id,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        member_id = response.json()["id"]
        self.assertEqual(response.json()["username"], "member01")
        self.assertEqual(response.json()["display_name"], "普通成员")
        self.assertEqual(response.json()["contact"], "13800000000")
        self.assertTrue(Membership.objects.get(user_id=member_id).is_active)

        response = self.client.patch(
            f"/api/organizations/members/{member_id}/",
            {"display_name": "普通成员甲", "contact": "微信 member-wx"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["display_name"], "普通成员甲")
        self.assertEqual(response.json()["contact"], "微信 member-wx")
        self.assertEqual(User.objects.get(pk=member_id).contact, "微信 member-wx")

        response = self.client.patch(
            f"/api/organizations/members/{member_id}/",
            {"is_active": False},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])

        response = self.client.patch(
            f"/api/organizations/members/{member_id}/",
            {"is_active": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_active"])

        response = self.client.delete(f"/api/organizations/members/{member_id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Membership.objects.filter(user_id=member_id).exists())
        self.assertTrue(AuditLog.objects.filter(action="member.removed").exists())

    def test_owner_can_edit_and_delete_custom_role(self):
        response = self.client.post(
            "/api/organizations/roles/",
            {
                "code": "sales",
                "name": "销售",
                "description": "负责客户跟进",
                "permissions": ["feature.read"],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        role_id = response.json()["id"]
        self.assertEqual(response.json()["description"], "负责客户跟进")
        response = self.client.patch(
            f"/api/organizations/roles/{role_id}/",
            {"name": "销售主管", "permissions": ["feature.read", "feature.create"]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["permissions"], ["feature.create", "feature.read"])
        self.assertEqual(self.client.delete(f"/api/organizations/roles/{role_id}/").status_code, 204)

    def test_role_manager_can_only_grant_permissions_they_have(self):
        manager_role = Role.objects.create(
            organization=self.organization,
            code="role-manager",
            name="角色管理员",
        )
        manager_role.permissions.add(Permission.objects.get(code="role.manage"))
        manager = User.objects.create_user(
            "role-manager",
            "test-password-123",
            display_name="角色管理员",
            contact="manager-contact",
        )
        Membership.objects.create(organization=self.organization, user=manager, role=manager_role)
        manager_client = self.client.__class__()
        manager_client.force_login(manager)

        catalog = manager_client.get("/api/organizations/permissions/")
        self.assertEqual(catalog.status_code, 200)
        catalog_by_code = {item["code"]: item for item in catalog.json()}
        self.assertTrue(catalog_by_code["role.manage"]["assignable"])
        self.assertFalse(catalog_by_code["ai.configure"]["assignable"])

        response = manager_client.post(
            "/api/organizations/roles/",
            {"code": "unsafe-role", "name": "越权角色", "permissions": ["ai.configure"]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Role.objects.filter(organization=self.organization, code="unsafe-role").exists())

    def test_role_manager_cannot_assign_a_higher_permission_role_to_member(self):
        manager_role = Role.objects.create(
            organization=self.organization,
            code="member-manager",
            name="成员管理员",
        )
        manager_role.permissions.add(Permission.objects.get(code="member.manage"))
        manager = User.objects.create_user(
            "member-manager",
            "test-password-123",
            display_name="成员管理员",
            contact="member-manager-contact",
        )
        Membership.objects.create(organization=self.organization, user=manager, role=manager_role)
        manager_client = self.client.__class__()
        manager_client.force_login(manager)
        admin_role = Role.objects.get(organization=self.organization, code="admin")

        response = manager_client.post(
            "/api/organizations/members/",
            {
                "username": "new-member",
                "display_name": "新成员",
                "contact": "new-member-contact",
                "password": "new-member-password",
                "role_id": admin_role.id,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="new-member").exists())

    def test_member_cannot_manage_members_or_roles(self):
        member = User.objects.create_user(
            "ordinary01",
            "test-password-123",
            display_name="普通成员",
            contact="ordinary-contact",
        )
        member_role = Role.objects.get(organization=self.organization, code="member")
        Membership.objects.create(organization=self.organization, user=member, role=member_role)
        ordinary_client = self.client.__class__()
        ordinary_client.force_login(member)

        self.assertEqual(ordinary_client.get("/api/organizations/members/").status_code, 200)
        self.assertEqual(
            ordinary_client.post(
                "/api/organizations/members/",
                {"username": "blocked01", "password": "blocked-password-123", "role_id": member_role.id},
                content_type="application/json",
            ).status_code,
            403,
        )
        self.assertEqual(ordinary_client.get("/api/organizations/roles/").status_code, 403)
        self.assertEqual(
            ordinary_client.post(
                "/api/organizations/",
                {"name": "无权子组织", "parent_id": str(self.organization.id)},
                content_type="application/json",
            ).status_code,
            403,
        )

    def test_member_permissions_are_enforced_at_menu_api_boundaries(self):
        viewer_role = Role.objects.create(
            organization=self.organization,
            code="viewer",
            name="只读成员",
        )
        viewer_role.permissions.add(Permission.objects.get(code="member.read"))
        viewer = User.objects.create_user(
            "viewer01",
            "test-password-123",
            display_name="只读成员",
            contact="viewer-contact",
        )
        Membership.objects.create(organization=self.organization, user=viewer, role=viewer_role)
        viewer_client = self.client.__class__()
        viewer_client.force_login(viewer)

        self.assertEqual(viewer_client.get("/api/organizations/members/").status_code, 200)
        self.assertEqual(viewer_client.get("/api/organizations/roles/").status_code, 403)
        self.assertEqual(viewer_client.get("/api/organizations/audit-logs/").status_code, 403)
        self.assertEqual(viewer_client.get("/api/ai/config/").status_code, 403)

    def test_owner_can_create_another_organization(self):
        response = self.client.post(
            "/api/organizations/",
            {"name": "第二个组织"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["name"], "第二个组织")
        self.assertIsNone(response.json()["parent_id"])
        self.assertTrue(
            Membership.objects.filter(
                organization__name="第二个组织",
                user=self.owner,
                is_owner=True,
            ).exists()
        )

    def test_owner_can_create_child_organization(self):
        response = self.client.post(
            "/api/organizations/",
            {"name": "华东分部", "parent_id": str(self.organization.id)},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["parent_id"], str(self.organization.id))
        self.assertEqual(response.json()["path"], "管理组织 / 华东分部")

    def test_child_organization_requires_access_to_manage_the_parent(self):
        other_user = User.objects.create_user("other-owner", "test-password-123")
        other_organization = create_organization(user=other_user, name="其他组织")

        response = self.client.post(
            "/api/organizations/",
            {"name": "越权子组织", "parent_id": str(other_organization.id)},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_owner_cannot_remove_owner(self):
        response = self.client.delete(f"/api/organizations/members/{self.owner.id}/")
        self.assertEqual(response.status_code, 400)
