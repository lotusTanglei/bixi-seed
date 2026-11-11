"""Independent E6 TOCTOU reproduction and repair check; ephemeral DB only."""
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

with tempfile.TemporaryDirectory(prefix='bixi-seed-model-review-') as review_dir:
    os.environ['BIXI_DATA_DIR'] = review_dir
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    import django
    django.setup()
    from django.test.runner import DiscoverRunner
    from ai.tests.test_tool_calls import ControlledToolApiTest
    from ai.models import ToolCallProposal
    from accounts.models import User
    from organizations.models import Membership, Permission, Role

    class ModelReview(ControlledToolApiTest):
        def revoked_plan(self, revoke_membership=False):
            role = Role.objects.create(organization=self.organization, code='model-review', name='model reviewer')
            role.permissions.set(Permission.objects.filter(code__in=['ai.use', 'feature.update']))
            user = User.objects.create_user('model-review', 'test-password-123')
            membership = Membership.objects.create(organization=self.organization, user=user, role=role)
            client = self.client.__class__()
            client.force_login(user)
            record = self.record()
            def revoke_during_model(messages, tools):
                if revoke_membership:
                    membership.delete()
                else:
                    role.permissions.remove(Permission.objects.get(code='ai.use'))
                return {'name': 'feature_record_update', 'arguments': {'feature_id': str(self.feature.pk), 'record_id': record.pk, 'data': {'name': 'after'}}}
            provider = Mock()
            provider.complete_tool_call.side_effect = revoke_during_model
            with patch('ai.views.get_provider', return_value=provider):
                response = client.post('/api/ai/tool-plan/', {'feature_id': str(self.feature.pk), 'requirement': 'update selected record'}, content_type='application/json')
            print('REVOKE_MEMBERSHIP', revoke_membership, 'PLAN_STATUS', response.status_code)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn('preview', response.json())
            self.assertFalse(ToolCallProposal.objects.exists())
            record.refresh_from_db()
            self.assertEqual(record.data, {'name': 'before'})

        def test_ai_permission_revocation_during_model_call(self):
            self.revoked_plan()

        def test_membership_revocation_during_model_call(self):
            self.revoked_plan(revoke_membership=True)

    runner = DiscoverRunner(verbosity=0)
    runner.setup_test_environment()
    old_config = runner.setup_databases()
    try:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(ModelReview(name) for name in [
            'test_ai_permission_revocation_during_model_call',
            'test_membership_revocation_during_model_call',
        ]))
    finally:
        runner.teardown_databases(old_config)
        runner.teardown_test_environment()
    raise SystemExit(0 if result.wasSuccessful() else 1)
