import json
from importlib import metadata
from unittest.mock import patch

from django.test import TestCase

from accounts.models import User
from extensions.models import ExtensionDraft
from organizations.models import AuditLog, Membership, Permission, Role
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class ExtensionDraftApiTest(TestCase):
    def setUp(self):
        Permission.objects.bulk_create(
            [Permission(code=code, name=name, description=description) for code, name, description in DEFAULT_PERMISSIONS]
        )
        self.user = User.objects.create_user("extension-owner", "test-password-123")
        self.organization = create_organization(user=self.user, name="扩展组织")
        self.client.force_login(self.user)

    def create_draft(self, **changes):
        payload = {
            "key": "customer-extension", "name": "客户扩展",
            "files": {"extension.py": "from decimal import Decimal\nvalue = Decimal('1.0')\n", "manifest.json": '{"version": 1}'},
            "dependencies": ["packaging>=24,<27"], "permission_manifest": ["feature.read"],
        }
        payload.update(changes)
        return self.client.post("/api/extensions/drafts/", payload, content_type="application/json")

    def enable(self, draft, **changes):
        payload = {"confirmed": True, "content_hash": draft["validated_hash"]}
        payload.update(changes)
        return self.client.post(f'/api/extensions/drafts/{draft["id"]}/enable/', payload, content_type="application/json")

    def login_manager(self, permissions):
        user = User.objects.create_user("extension-manager", "test-password-123")
        role = Role.objects.create(organization=self.organization, code="extension-manager", name="扩展管理")
        role.permissions.set(Permission.objects.filter(code__in=permissions))
        Membership.objects.create(organization=self.organization, user=user, role=role)
        self.client.force_login(user)
        return role

    def test_validated_draft_requires_confirmation_and_never_executes_code(self):
        response = self.create_draft(files={"extension.py": "raise RuntimeError('must not execute')\n"})
        self.assertEqual(response.status_code, 201)
        draft = response.json()
        self.assertEqual(draft["status"], "validated")
        self.assertEqual(draft["isolation_status"], "not_executed")
        self.assertEqual(len(draft["validated_hash"]), 64)
        self.assertNotIn("unit_test", draft["static_checks"])
        self.assertNotIn("build", draft["static_checks"])
        self.assertNotIn("isolation_ready", draft["static_checks"])
        response = self.enable(draft)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "enabled")
        self.assertEqual(response.json()["execution_status"], "not_loaded_or_executed")
        self.assertEqual(response.json()["enabled_hash"], draft["validated_hash"])
        log = AuditLog.objects.get(action="extension.draft.enabled")
        self.assertEqual(log.actor_id, self.user.pk)
        self.assertEqual(log.organization_id, self.organization.pk)
        self.assertEqual(log.metadata["content_hash"], draft["validated_hash"])
        self.assertEqual(log.metadata["permission_manifest"], ["feature.read"])

    def test_traversal_windows_ambiguous_paths_and_unknown_code_are_rejected(self):
        for path in ["../run.py", "safe/../run.py", r"safe\run.py", "C:/run.py", "/run.py", "a//run.py", "./run.py", ".", "run.js", "run.py\x00"]:
            with self.subTest(path=path):
                self.assertEqual(self.create_draft(files={path: "value = 1"}).status_code, 400)
        self.assertFalse(ExtensionDraft.objects.exists())

    def test_ast_rejects_syntax_dangerous_aliases_reflection_and_undeclared_imports(self):
        for content in ["def broken(: pass", "import os as safe\nsafe.system('x')", "from subprocess import run as safe\nsafe('x')", "f = eval\nf('x')", "value = ().__class__", "import missing_library", "from math import __loader__", "from . import helper", "import json\njson.codecs.open('x', 'w')", "from typing import sys as runtime\nruntime.modules['os'].system('x')"]:
            with self.subTest(content=content):
                self.assertEqual(self.create_draft(files={"run.py": content}).status_code, 400)

    def test_static_checks_accept_harmless_text_and_never_import_draft(self):
        response = self.create_draft(files={"run.py": 'description = "subprocess eval( is only text"\n'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["static_checks"]["static_check"], "passed")

    def test_dependency_names_versions_urls_and_environment_markers_are_checked(self):
        for dependencies in [["bixi-missing-package==1"], ["packaging<1"], ["packaging @ https://example.com/pkg.whl"], ["packaging; python_version>'1'"], ["packaging[extra]"], ["packaging", "Packaging"], ["not a requirement!"]]:
            with self.subTest(dependencies=dependencies):
                self.assertEqual(self.create_draft(dependencies=dependencies).status_code, 400)
        response = self.create_draft()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["static_checks"]["installed_dependencies"][0]["version"], metadata.version("packaging"))

    def test_unknown_permission_and_permissions_outside_actor_grants_are_rejected(self):
        self.assertEqual(self.create_draft(permission_manifest=["unknown.permission"]).status_code, 400)
        self.login_manager(["feature.manage"])
        response = self.create_draft(permission_manifest=["organization.manage"])
        self.assertEqual(response.status_code, 400)
        self.assertIn("超出当前用户", str(response.json()))
        self.assertEqual(self.create_draft(permission_manifest={"organization": "all"}).status_code, 400)

    def test_enable_requires_literal_confirmation_and_reviewed_hash(self):
        draft = self.create_draft().json()
        for changes in [{"confirmed": False}, {"confirmed": "true"}, {"confirmed": 1}, {"content_hash": "old"}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.enable(draft, **changes).status_code, 409)
        item = ExtensionDraft.objects.get(pk=draft["id"])
        self.assertEqual(item.status, "validated")
        self.assertIsNone(item.enabled_at)
        self.assertEqual(AuditLog.objects.filter(action="extension.draft.enable_denied", success=False).count(), 4)

    def test_content_change_invalidates_confirmation_until_revalidated(self):
        draft = self.create_draft().json()
        ExtensionDraft.objects.filter(pk=draft["id"]).update(files={"run.py": "value = 2"})
        self.assertEqual(self.enable(draft).status_code, 409)
        validated = self.client.post(f'/api/extensions/drafts/{draft["id"]}/validate/').json()
        self.assertNotEqual(validated["validated_hash"], draft["validated_hash"])
        self.assertEqual(self.enable(validated).status_code, 200)

    def test_enable_rechecks_dependencies_and_revoked_permissions(self):
        role = self.login_manager(["feature.manage", "feature.read"])
        draft = self.create_draft().json()
        role.permissions.remove(Permission.objects.get(code="feature.read"))
        response = self.enable(draft)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["draft"]["static_checks"]["permission_check"], "failed")
        self.client.force_login(self.user)
        draft = self.create_draft(key="dependency-recheck").json()
        with patch("extensions.services.metadata.version", side_effect=metadata.PackageNotFoundError):
            response = self.enable(draft)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["draft"]["static_checks"]["dependency_check"], "failed")

    def test_catalog_is_org_scoped_and_non_managers_cannot_access(self):
        draft = self.create_draft().json()
        other = User.objects.create_user("other-extension-owner", "test-password-123")
        create_organization(user=other, name="别的组织")
        self.client.force_login(other)
        self.assertEqual(self.client.get("/api/extensions/drafts/").json(), [])
        self.assertEqual(self.enable(draft).status_code, 404)
        self.assertEqual(self.client.post(f'/api/extensions/drafts/{draft["id"]}/validate/').status_code, 404)
        self.login_manager(["feature.read"])
        self.assertEqual(self.client.get("/api/extensions/drafts/").status_code, 403)
        self.assertEqual(self.enable(draft).status_code, 403)

    def test_permission_manifest_change_changes_hash_and_invalid_json_is_rejected(self):
        self.assertEqual(self.create_draft(files={"manifest.json": "{"}).status_code, 400)
        draft = self.create_draft().json()
        ExtensionDraft.objects.filter(pk=draft["id"]).update(permission_manifest=["audit.read"])
        self.assertEqual(self.enable(draft).status_code, 409)

    def test_oversized_and_invalid_utf8_content_fail_closed(self):
        for content in ["a" * (100 * 1024 + 1), "\ud800"]:
            with self.subTest(size=len(content)):
                self.assertEqual(self.create_draft(files={"run.py": content}).status_code, 400)

    def test_escaped_surrogates_in_paths_and_metadata_return_400(self):
        for changes in [{"files": {"\ud800.py": "value = 1"}}, {"key": "\ud800"}, {"name": "\ud800"}, {"description": "\ud800"}, {"permission_manifest": ["\ud800"]}]:
            with self.subTest(field=list(changes)[0]):
                payload = {"key": "unicode-check", "name": "Unicode 检查", "files": {"run.py": "value = 1"}}
                payload.update(changes)
                response = self.client.post("/api/extensions/drafts/", json.dumps(payload), content_type="application/json")
                self.assertEqual(response.status_code, 400)
                self.assertIsNotNone(response.json()["detail"])
