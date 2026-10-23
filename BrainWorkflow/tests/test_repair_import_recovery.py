import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.test_workflow_stage_outcomes import checked_alpha, write_rows
from wqb.workflow_stage_adapters import advance_post_schedule_stage


def fixture(root):
    """Input: temporary Path. Output: receipt/child dicts. Build actual import-to-Repair lineage."""
    parent = checked_alpha()
    write_rows(root, [parent])
    source = root / 'all_alphas.jsonl'
    imported = hashlib.sha256(source.read_bytes()).hexdigest()
    for relative, value in (
        ('stages/scout_seed/scout_seed_import.json', {'target_run_id': root.name, 'imported_artifacts': [{'name': 'all_alphas.jsonl', 'sha256': imported}]}),
        ('stages/batch_generation/discovery_execution.json', {'run_id': root.name, 'status': 'completed',
            'input_sha256': imported, 'output_sha256': imported}),
        ('stages/backtest/check_recovery.json', {'run_id': root.name, 'status': 'completed',
            'input_sha256': imported, 'output_sha256': imported})):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
    weak = checked_alpha('weak', alpha_id='weak', expression_hash='weak-hash')
    write_rows(root, [parent, weak])
    discovery_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    weak['metrics']['fitness'] = .01
    write_rows(root, [parent, weak])
    check_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    for relative, before, after in (
        ('stages/batch_generation/discovery_execution.json', imported, discovery_digest),
        ('stages/backtest/check_recovery.json', discovery_digest, check_digest)):
        path = root / relative
        value = json.loads(path.read_text())
        value.update(input_sha256=before, output_sha256=after)
        path.write_text(json.dumps(value))
    saved = checked_alpha('qualified', alpha_id='child', expression='rank(cash)', settings={'decay': 8})
    child = saved | {'settings': {'decay': 8, 'simulationMode': 'FULL'},
                     'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash']}
    for row in (saved, child):
        row['expression_hash'] = hashlib.sha256(json.dumps([row['expression'], row['settings']], sort_keys=True).encode()).hexdigest()
    write_rows(root, [parent, weak, saved])
    journal = root / 'stages/repair/parents/p/iterations/one/all_alphas.jsonl'
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps(child) + '\n', encoding='utf-8')
    receipt = {'run_id': root.name, 'status': 'paused', 'scheduler_version': 1, 'recovery_eligible': False,
        'input_sha256': check_digest, 'last_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'max_simulations': 1, 'parent_keys': [[parent['alpha_id'], parent['expression_hash']]],
        'blocker': 'ValueError: Repair child identity collision', 'attempts': [{
            'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash'],
            'phase': 'blocked', 'blocker': 'ValueError: Repair child identity collision', 'max_simulations': 1,
            'children': [], 'plan': {'variants': [{'expression_hash': child['expression_hash']}]}}]}
    path = root / 'stages/repair/repair_execution.json'
    path.write_text(json.dumps(receipt), encoding='utf-8')
    return receipt, child


class RepairImportRecoveryTests(unittest.TestCase):
    def test_verified_output_contract_failure_reaches_repaired_planner(self):
        for suffix in ('', '; Repair planning failed: RepairPlanningBlocked: AI Repair action must be test or stop',
                       '; unknown fault'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                receipt, child = fixture(root)
                receipt['blocker'] = 'Repair planning failed: RepairPlanningBlocked: AI Repair action must be test or stop' + suffix
                receipt['attempts'][0].update(phase='checked', blocker='', children=[child])
                (root / 'stages/repair/repair_execution.json').write_text(json.dumps(receipt))
                executor = Mock(supports_ai_planning=True, supports_durable_recovery=True)
                with patch('wqb.workflow_stage_adapters._execute_repair', return_value={'blocker': 'reached planner'}) as execute:
                    advance_post_schedule_stage(root, 'repair', repair_executor=executor)
                self.assertEqual(execute.call_count, 0 if suffix.endswith('unknown fault') else 1)

    def test_verified_context_failure_reaches_repaired_planner_after_restart(self):
        for kind in ('valid', 'unknown_fault', 'broken_chain', 'blocked_attempt', 'tampered_root'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                receipt, child = fixture(root)
                receipt['blocker'] = ('Repair planning failed: RepairPlanningBlocked: '
                    'AI Repair context exceeds bounded evidence input; compile concise semantics')
                receipt['attempts'][0].update(phase='checked', blocker='', children=[child])
                if kind == 'unknown_fault':
                    receipt['blocker'] = 'unknown planning fault'
                elif kind == 'broken_chain':
                    receipt['input_sha256'] = 'wrong'
                elif kind == 'blocked_attempt':
                    receipt['attempts'][0].update(phase='blocked', blocker='unknown fault')
                elif kind == 'tampered_root':
                    with (root / 'all_alphas.jsonl').open('a') as stream:
                        stream.write(json.dumps(checked_alpha('weak', alpha_id='foreign')) + '\n')
                (root / 'stages/repair/repair_execution.json').write_text(json.dumps(receipt))
                executor = Mock(supports_ai_planning=True, supports_durable_recovery=True)
                with patch('wqb.workflow_stage_adapters._execute_repair', return_value={
                        'blocker': 'reached planner', 'status': 'paused'}) as execute:
                    result = advance_post_schedule_stage(root, 'repair', repair_executor=executor)
                self.assertEqual(execute.call_count, 1 if kind == 'valid' else 0)
                self.assertEqual(result['status'], 'paused')

    def test_import_contract_fault_routes_maintenance_without_stale_repair_receipt(self):
        from wqb.workflow_driver import _repair_cooldown_result
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            result = _repair_cooldown_result(root, {'current_stage': 'repair', 'status': 'paused',
                'pause_reason': 'checked research differs from its import receipt', 'next_action': 'workflow-resume'},
                '2026-10-13T00:00:00Z')
            self.assertEqual(result['next_action'], 'maintenance-blocker')

    def test_adapter_reaches_cached_recovery_and_restart_without_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            original = (root / 'all_alphas.jsonl').read_bytes()
            executor = Mock(supports_ai_planning=True, supports_durable_recovery=True)
            for _ in range(2):
                result = advance_post_schedule_stage(root, 'repair', repair_executor=executor, repair_max_simulations=1)
                self.assertEqual(result['status'], 'completed', result.get('blocker'))
            executor.assert_not_called()
            executor.prepare.assert_not_called()
            self.assertEqual(original, (root / 'all_alphas.jsonl').read_bytes())
            receipt = json.loads((root / 'stages/repair/repair_execution.json').read_text())
            self.assertEqual(receipt['attempts'][0]['phase'], 'checked')

    def test_bad_import_or_conflicting_journal_remains_blocked(self):
        for kind in ('import', 'journal', 'unknown_blocker', 'truncated_journal', 'check_chain'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                receipt, child = fixture(root)
                if kind == 'import':
                    receipt['input_sha256'] = 'wrong'
                elif kind == 'journal':
                    child['metrics']['sharpe'] = 99
                    next((root / 'stages/repair/parents').glob('**/all_alphas.jsonl')).write_text(json.dumps(child) + '\n')
                elif kind == 'truncated_journal':
                    next((root / 'stages/repair/parents').glob('**/all_alphas.jsonl')).write_text('{broken')
                elif kind == 'check_chain':
                    path = root / 'stages/backtest/check_recovery.json'
                    value = json.loads(path.read_text())
                    value['input_sha256'] = 'wrong'
                    path.write_text(json.dumps(value))
                else:
                    receipt['attempts'][0]['blocker'] = 'unknown fault'
                (root / 'stages/repair/repair_execution.json').write_text(json.dumps(receipt))
                executor = Mock(supports_ai_planning=True, supports_durable_recovery=True)
                result = advance_post_schedule_stage(root, 'repair', repair_executor=executor, repair_max_simulations=1)
                self.assertEqual(result['status'], 'paused')
                executor.assert_not_called()
                executor.prepare.assert_not_called()
