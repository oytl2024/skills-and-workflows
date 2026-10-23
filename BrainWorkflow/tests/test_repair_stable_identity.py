import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from wqb.expression import expression_hash
from wqb.repair_scheduler import verified_platform_alias, execute_repair_round


def row(legacy=False):
    """Input: legacy flag bool. Output: checked dict. Represent one simulation under either genuine hash scheme."""
    result = {'alpha_id': 'alpha', 'expression': 'rank(cash)', 'settings': {'decay': 8},
        'status': 'CHECKED', 'failed': ['LOW_FITNESS'], 'pending': [], 'hard_pass': False,
        'metrics': {'sharpe': .9, 'fitness': .4, 'turnover': .1,
                    'checks': [{'name': 'LOW_FITNESS', 'result': 'FAIL', 'limit': 1, 'value': .4}]}}
    result['expression_hash'] = (expression_hash(result['expression'] + '\n' + json.dumps(result['settings'], ensure_ascii=False, sort_keys=True))
        if legacy else hashlib.sha256(json.dumps([result['expression'], result['settings']], sort_keys=True).encode()).hexdigest())
    return result


class RepairStableIdentityTests(unittest.TestCase):
    def test_numeric_json_type_changes_cannot_alias_or_reuse(self):
        from wqb.repair_identity import matching_simulation_rows
        old, fresh = row(True), row()
        old['metrics']['checks'][0]['value'] = 0
        fresh['metrics']['checks'][0]['value'] = False
        self.assertFalse(verified_platform_alias(old, fresh))

    def test_settings_numeric_representation_cannot_create_invalid_reuse_child(self):
        from wqb.repair_identity import matching_simulation_rows
        old, fresh = row(True), row()
        old['settings']['decay'] = 8.0
        old['expression_hash'] = expression_hash(old['expression'] + '\n' + json.dumps(old['settings'], ensure_ascii=False, sort_keys=True))
        self.assertIsNone(matching_simulation_rows([old], fresh))

    def test_adapter_recovers_legacy_activity_collision_without_post_or_append(self):
        from tests import test_repair_import_recovery as fixtures
        from wqb.workflow_stage_adapters import advance_post_schedule_stage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt, child = fixtures.fixture(root)
            source = root / 'all_alphas.jsonl'
            rows = [json.loads(line) for line in source.read_text().splitlines()]
            saved = rows[-1]
            saved['settings'] = child['settings']
            for item in (saved, child):
                item.update(hard_pass=False, failed=['LOW_FITNESS'], pending=[])
                item['metrics'] = {'sharpe': .9, 'fitness': .4, 'turnover': .1,
                    'checks': [{'name': 'LOW_FITNESS', 'result': 'FAIL', 'value': .4, 'limit': 1}]}
            saved['expression_hash'] = expression_hash(saved['expression'] + '\n' + json.dumps(saved['settings'], ensure_ascii=False, sort_keys=True))
            saved['metrics']['checks'].append({'name': 'MATCHES_THEMES', 'result': 'WARNING', 'themes': ['old']})
            child['metrics']['checks'].append({'name': 'MATCHES_THEMES', 'result': 'WARNING', 'themes': ['new']})
            source.write_text(''.join(json.dumps(item) + '\n' for item in rows))
            original = source.read_bytes()
            receipt['last_sha256'] = hashlib.sha256(original).hexdigest()
            (root / 'stages/repair/repair_execution.json').write_text(json.dumps(receipt))
            next((root / 'stages/repair/parents').glob('**/all_alphas.jsonl')).write_text(json.dumps(child) + '\n')
            executor = Mock(supports_ai_planning=True, supports_durable_recovery=True)
            result = advance_post_schedule_stage(root, 'repair', repair_executor=executor, repair_max_simulations=1)
            self.assertEqual(result['status'], 'completed', result.get('blocker'))
            executor.assert_not_called()
            executor.prepare.assert_not_called()
            self.assertEqual(source.read_bytes(), original)
            updated = json.loads((root / 'stages/repair/repair_execution.json').read_text())
            self.assertEqual(updated['attempts'][0]['children'][0]['metrics'], child['metrics'])
            self.assertFalse(updated['attempts'][0]['children'][0]['hard_pass'])

    def test_legacy_hash_and_activity_snapshot_differences_are_research_aliases(self):
        old, fresh = row(True), row()
        old['metrics']['checks'].append({'name': 'MATCHES_COMPETITION', 'result': 'WARNING', 'competitions': ['old']})
        old['metrics']['checks'].append({'name': 'MATCHES_THEMES', 'result': 'WARNING', 'themes': ['old']})
        fresh['metrics']['checks'].append({'name': 'MATCHES_THEMES', 'result': 'WARNING', 'themes': ['new']})
        self.assertTrue(verified_platform_alias(old, fresh))
        for change in ('unknown_hash', 'metric', 'stable_check', 'activity_fail', 'qualified', 'settings'):
            modified = json.loads(json.dumps(fresh))
            if change == 'unknown_hash': modified['expression_hash'] = 'arbitrary'
            elif change == 'metric': modified['metrics']['sharpe'] = 2
            elif change == 'stable_check': modified['metrics']['checks'][0]['value'] = .5
            elif change == 'activity_fail': modified['metrics']['checks'][-1]['result'] = 'FAIL'
            elif change == 'qualified': modified['hard_pass'] = True
            elif change == 'settings': modified['settings']['decay'] = 9
            with self.subTest(change=change):
                self.assertFalse(verified_platform_alias(old, modified))
        for candidate in (old, fresh):
            candidate.update(hard_pass=True, failed=[], pending=[])
        self.assertFalse(verified_platform_alias(old, fresh), 'activity-filtered research must never supply qualification')

    def test_conflicting_canonical_duplicate_blocks_before_simulation(self):
        for kind in ('invalid_hash', 'mixed_metrics', 'different_platform_id'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent = row()
                parent.update(alpha_id='parent', expression_hash='parent-hash', benchmark_label='repairable_signal')
                parent['settings'] = {'decay': 4}
                saved, extra = row(True), row()
                if kind == 'invalid_hash': saved['expression_hash'] = 'unverified'
                elif kind == 'mixed_metrics': extra['metrics']['sharpe'] = 2
                else: extra['alpha_id'] = 'other'
                (root / 'all_alphas.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (parent, saved, extra)))
                executor = Mock()
                executor.prepare.return_value = {'variants': [row()], 'evidence_digest': 'plan', 'decision': {}}
                result = execute_repair_round(root, {'rows': [parent]}, executor, 1)
                executor.assert_not_called()
                self.assertEqual(result['status'], 'paused')
                self.assertEqual(result['budget_reserved'], 0)
                self.assertIn('conflicts', result['blocker'])

    def test_pre_submit_dedupe_reuses_legacy_result_without_simulation_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = row()
            parent.update(alpha_id='parent', expression_hash='parent-hash', benchmark_label='repairable_signal')
            parent['settings'] = {'decay': 4}
            saved = row(True)
            saved['parent_alpha_id'] = 'other'
            (root / 'all_alphas.jsonl').write_text(json.dumps(parent) + '\n' + json.dumps(saved) + '\n')
            original = (root / 'all_alphas.jsonl').read_bytes()
            child = row() | {'parent_alpha_id': 'parent', 'parent_expression_hash': 'parent-hash'}
            executor = Mock()
            executor.prepare.return_value = {'variants': [child], 'evidence_digest': 'plan', 'decision': {}}
            result = execute_repair_round(root, {'rows': [parent, saved]}, executor, 1)
            executor.assert_not_called()
            self.assertEqual(result['budget_reserved'], 0)
            self.assertEqual(result['attempts'][0]['children'][0]['alpha_id'], 'alpha')
            self.assertTrue(result['attempts'][0]['reused_existing_simulation'])
            self.assertEqual((root / 'all_alphas.jsonl').read_bytes(), original)
            receipt_path = root / 'stages/repair/repair_execution.json'
            corrupted = json.loads(receipt_path.read_text())
            corrupted['attempts'][0]['children'][0]['metrics']['sharpe'] = 10
            receipt_path.write_text(json.dumps(corrupted))
            invalid = execute_repair_round(root, {'rows': [parent, saved]}, executor, 1)
            self.assertEqual(invalid.get('status'), 'paused')
            self.assertIn('reuse evidence', invalid['blocker'])
            receipt_path.write_text(json.dumps(result))
            execute_repair_round(root, {'rows': [parent, saved]}, executor, 1)
            executor.assert_not_called()
            updated = json.loads((root / 'stages/repair/repair_execution.json').read_text())
            self.assertEqual(len(updated['attempts']), 1)
