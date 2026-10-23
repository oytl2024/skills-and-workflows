import hashlib
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock


class RepairAliasTests(unittest.TestCase):
    def test_blocked_alias_recovers_from_checked_journal_without_executor_or_root_append(self):
        from wqb.repair_scheduler import execute_repair_round
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = {'alpha_id': 'parent', 'expression_hash': 'parent-hash', 'benchmark_label': 'repairable_signal'}
            saved = {'alpha_id': 'child', 'expression': 'rank(cash)', 'settings': {'decay': 8},
                     'metrics': {}, 'failed': [], 'pending': [], 'hard_pass': False, 'status': 'CHECKED',
                     'parent_alpha_id': 'other', 'parent_expression_hash': 'other-hash'}
            child = {**saved, 'settings': {'decay': 8, 'simulationMode': 'FULL'},
                     'parent_alpha_id': 'parent', 'parent_expression_hash': 'parent-hash'}
            for row in (saved, child):
                row['expression_hash'] = hashlib.sha256(json.dumps([row['expression'], row['settings']], sort_keys=True).encode()).hexdigest()
            source = root / 'all_alphas.jsonl'
            source.write_text(json.dumps(parent) + '\n' + json.dumps(saved) + '\n', encoding='utf-8')
            original = source.read_bytes()
            digest = hashlib.sha256(original).hexdigest()
            journal = root / 'stages/repair/parents/parent/iterations/one/all_alphas.jsonl'
            journal.parent.mkdir(parents=True)
            journal.write_text(json.dumps(child) + '\n', encoding='utf-8')
            receipt = {'run_id': root.name, 'status': 'paused', 'input_sha256': digest, 'last_sha256': digest,
                       'max_simulations': 1, 'parent_keys': [['parent', 'parent-hash']],
                       'attempts': [{'parent_alpha_id': 'parent', 'parent_expression_hash': 'parent-hash',
                                     'max_simulations': 1, 'phase': 'blocked', 'children': [],
                                     'blocker': 'ValueError: Repair child identity collision',
                                     'plan': {'variants': [{'expression_hash': child['expression_hash']}]}}]}
            path = root / 'stages/repair/repair_execution.json'
            path.write_text(json.dumps(receipt), encoding='utf-8')
            executor = Mock()
            result = execute_repair_round(root, {'rows': [parent]}, executor, 1)
            executor.assert_not_called()
            executor.prepare.assert_not_called()
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['attempts'][0]['children'], [child])
            self.assertEqual(len(result['publication_aliases']), 1)
            again = execute_repair_round(root, {'rows': [parent]}, executor, 1)
            self.assertEqual(len(again['publication_aliases']), 1)

    def test_mixed_alias_and_true_conflict_is_rejected_in_either_order(self):
        from wqb.repair_scheduler import publication_matches
        row = {'alpha_id': 'a', 'expression_hash': 'hash'}
        conflict = {**row, 'alpha_id': 'different'}
        for known in ([row, conflict], [conflict, row]):
            self.assertIsNone(publication_matches(known, row))
        self.assertEqual(publication_matches([row], row), [row])
        self.assertEqual(publication_matches([], row), [])

    def test_same_platform_result_with_expanded_settings_keeps_both_lineages(self):
        from wqb.repair_scheduler import verified_platform_alias
        row = {'alpha_id': 'alpha', 'expression': 'rank(cash)', 'settings': {'decay': 8},
               'metrics': {'sharpe': 1, 'candidate_evidence': {'checked_at': 1}},
               'failed': [], 'pending': [], 'hard_pass': False, 'status': 'CHECKED', 'parent_alpha_id': 'a'}
        child = {**row, 'settings': {'decay': 8, 'simulationMode': 'FULL'}, 'parent_alpha_id': 'b',
                 'metrics': {'sharpe': 1, 'candidate_evidence': {'checked_at': 2}}}
        for item in (row, child):
            item['expression_hash'] = hashlib.sha256(json.dumps([item['expression'], item['settings']], sort_keys=True).encode()).hexdigest()
        self.assertTrue(verified_platform_alias(row, child))
        self.assertFalse(verified_platform_alias(row, {**child, 'alpha_id': 'different'}))
        self.assertFalse(verified_platform_alias(row, {**child, 'metrics': {'sharpe': 2}}))
        self.assertFalse(verified_platform_alias(row, {**child, 'settings': {'decay': 9}}))
        self.assertFalse(verified_platform_alias(row, {**child, 'expression_hash': 'bad'}))
