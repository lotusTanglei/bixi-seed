"""Preservation proof using Django's isolated test database, never the user database."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ExtensionCatalogMigrationTest(TransactionTestCase):
    def test_upgrade_rollback_and_reupgrade_preserve_source_and_require_new_review(self):
        executor = MigrationExecutor(connection)
        leaves = executor.loader.graph.leaf_nodes()

        def migrate_extensions(version):
            targets = [target for target in leaves if target[0] != "extensions"]
            targets.append(("extensions", version))
            migration_executor = MigrationExecutor(connection)
            migration_executor.migrate(targets)
            return migration_executor.loader.project_state(targets).apps

        try:
            old_apps = migrate_extensions("0001_initial")
            User = old_apps.get_model("accounts", "User")
            Organization = old_apps.get_model("organizations", "Organization")
            Role = old_apps.get_model("organizations", "Role")
            Membership = old_apps.get_model("organizations", "Membership")
            OldDraft = old_apps.get_model("extensions", "ExtensionDraft")
            user = User.objects.create(username="migration-extension-owner", password="not-a-login-password")
            organization = Organization.objects.create(name="迁移证明组织", slug="migration-proof", created_by_id=user.pk)
            role = Role.objects.create(organization_id=organization.pk, code="owner", name="所有者")
            membership = Membership.objects.create(
                organization_id=organization.pk, user_id=user.pk, role_id=role.pk, is_owner=True,
            )
            source = {
                "organization_id": organization.pk,
                "created_by_id": user.pk,
                "key": "preserved-extension",
                "name": "源草稿",
                "description": "升级回退必须保留",
                "files": {"extension.py": "raise RuntimeError('draft must never execute')\n", "manifest.json": '{"version": 1}'},
                "dependencies": ["packaging>=24,<27"],
            }
            legacy = OldDraft.objects.create(
                **source, status="validated", isolation_status="ready",
                static_checks={"passed": True, "isolation_ready": True},
            )
            legacy_id = legacy.pk
            created_at = legacy.created_at

            def assert_source_preserved(item):
                for field, value in source.items():
                    self.assertEqual(getattr(item, field), value, field)
                self.assertEqual(item.created_at, created_at)

            def assert_review_invalidated(item):
                self.assertEqual(item.status, "draft")
                self.assertEqual(item.isolation_status, "not_executed")
                self.assertFalse(item.static_checks["passed"])
                self.assertNotIn("isolation_ready", item.static_checks)
                self.assertEqual(item.static_checks["execution_status"], "not_loaded_or_executed")
                self.assertEqual(item.permission_manifest, [])
                self.assertEqual(item.validated_hash, "")
                self.assertEqual(item.enabled_hash, "")
                self.assertIsNone(item.enabled_at)
                self.assertIsNone(item.enabled_by_id)

            new_apps = migrate_extensions("0002_controlled_catalog_review")
            upgraded = new_apps.get_model("extensions", "ExtensionDraft").objects.get(pk=legacy_id)
            assert_source_preserved(upgraded)
            assert_review_invalidated(upgraded)

            rolled_back_apps = migrate_extensions("0001_initial")
            rolled_back = rolled_back_apps.get_model("extensions", "ExtensionDraft").objects.get(pk=legacy_id)
            assert_source_preserved(rolled_back)
            # Schema rollback deliberately does not resurrect obsolete PASS evidence.
            self.assertEqual(rolled_back.status, "draft")
            self.assertFalse(rolled_back.static_checks["passed"])

            reupgraded_apps = migrate_extensions("0002_controlled_catalog_review")
            reupgraded = reupgraded_apps.get_model("extensions", "ExtensionDraft").objects.get(pk=legacy_id)
            assert_source_preserved(reupgraded)
            assert_review_invalidated(reupgraded)

            from extensions.models import ExtensionDraft
            from extensions.services import draft_content_hash, inspect_draft
            from extensions.views import save_review
            from organizations.models import Membership as CurrentMembership

            current = ExtensionDraft.objects.get(pk=legacy_id)
            current_membership = CurrentMembership.objects.select_related("role", "user").get(pk=membership.pk)
            checks = inspect_draft(
                key=current.key, files=current.files, dependencies=current.dependencies,
                permission_manifest=current.permission_manifest, membership=current_membership,
            )
            self.assertTrue(checks["passed"], checks["errors"])
            checks["content_hash"] = draft_content_hash(current)
            save_review(current, checks)
            current.refresh_from_db()
            assert_source_preserved(current)
            self.assertEqual(current.status, "validated")
            self.assertEqual(current.validated_hash, checks["content_hash"])
            self.assertEqual(len(current.validated_hash), 64)
            self.assertEqual(current.enabled_hash, "")
            self.assertEqual(current.isolation_status, "not_executed")
        finally:
            # Leave all apps at their leaf migrations before Django flushes the test DB.
            MigrationExecutor(connection).migrate(leaves)
