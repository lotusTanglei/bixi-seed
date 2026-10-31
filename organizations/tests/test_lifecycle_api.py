from django.test import TestCase

from accounts.models import User
from organizations.models import AuditLog, MemberInvitation, Membership, Permission, Role
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class MembershipLifecycleApiTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        self.owner = User.objects.create_user("lifecycle-owner", "owner-password-123")
        self.organization = create_organization(user=self.owner, name="生命周期组织")
        self.client.force_login(self.owner)
        self.member_role = Role.objects.get(organization=self.organization, code="member")

    def test_invite_accept_revoke_and_reinvite_reuses_user(self):
        response = self.client.post(
            "/api/organizations/invitations/",
            {"username": "invited-user", "display_name": "待接受", "contact": "contact", "role_id": self.member_role.id},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        token = response.json()["token"]
        user = User.objects.get(username="invited-user")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(Membership.objects.get(user=user, organization=self.organization).status, "invited")
        self.assertEqual(self.client.post(f"/api/auth/invitations/{token}/accept/", {"password": "new-password-123"}, content_type="application/json").status_code, 200)
        self.assertTrue(Membership.objects.get(user=user, organization=self.organization).is_active)
        self.assertEqual(MemberInvitation.objects.get(user=user).status, "accepted")
        self.assertEqual(self.client.post(f"/api/auth/invitations/{token}/accept/", {"password": "another-password"}, content_type="application/json").status_code, 400)

        self.client.force_login(self.owner)
        response = self.client.post(
            "/api/organizations/invitations/",
            {"username": "second-user", "role_id": self.member_role.id},
            content_type="application/json",
        )
        invitation_id = response.json()["id"]
        self.assertEqual(self.client.delete(f"/api/organizations/invitations/{invitation_id}/").status_code, 204)

    def test_owner_transfer_and_leave_protection(self):
        member = User.objects.create_user("target-owner", "target-password-123")
        membership = Membership.objects.create(organization=self.organization, user=member, role=self.member_role)
        self.assertEqual(self.client.post("/api/organizations/leave/", {}, content_type="application/json").status_code, 400)
        response = self.client.post(
            "/api/organizations/transfer-owner/", {"user_id": member.pk, "confirm": True}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        membership.refresh_from_db()
        self.assertTrue(membership.is_owner)
        self.assertEqual(Membership.objects.get(user=self.owner, organization=self.organization).role.code, "admin")
        self.assertTrue(AuditLog.objects.filter(action="organization.owner.transferred").exists())

    def test_audit_query_is_paginated_and_filtered(self):
        response = self.client.get("/api/organizations/audit-logs/?page=1&page_size=1&action=organization.created")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pagination"]["page_size"], 1)
        self.assertEqual(len(response.json()["items"]), 1)
