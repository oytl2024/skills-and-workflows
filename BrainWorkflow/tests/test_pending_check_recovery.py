import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from wqb.checker import fetch_check_summary
from wqb.models import CheckSummary, CheckItem
from wqb.pending_check_recovery import recover_pending_checks
from wqb.workflow_stage_adapters import research_evidence_blocker
from wqb.workflow_stage_adapters import advance_post_schedule_stage
from tests.test_workflow_stage_outcomes import checked_alpha, write_rows


class PendingCheckRecoveryTests(unittest.TestCase):
    def test_second_publication_interruption_accepts_previous_published_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [checked_alpha('qualified', hard_pass=False, pending=['SELF_CORRELATION'])])
            pending = CheckSummary('parent1', False, [], [], [CheckItem('SELF_CORRELATION', 'PENDING')], {})
            with patch('wqb.pending_check_recovery.CHECK_PENDING_RETRY_SECONDS', 0):
                recover_pending_checks(root, lambda identity: pending)
            with patch.object(Path, 'replace', side_effect=RuntimeError('power loss')):
                with self.assertRaises(RuntimeError):
                    recover_pending_checks(root, lambda identity: CheckSummary(identity, True, [], [], [], {}))
            recover_pending_checks(root, Mock(side_effect=AssertionError('must reuse terminal result')))
            row = json.loads((root / 'all_alphas.jsonl').read_text())
            self.assertTrue(row['hard_pass'])

    def test_pending_recheck_stops_at_three_and_does_not_make_extra_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [checked_alpha('qualified', hard_pass=False, pending=['SELF_CORRELATION'])])
            fetch = Mock(return_value=CheckSummary('parent1', False, [], [], [CheckItem('SELF_CORRELATION', 'PENDING')], {}))
            with patch('wqb.pending_check_recovery.CHECK_PENDING_RETRY_SECONDS', 0):
                for _ in range(5):
                    receipt = recover_pending_checks(root, fetch)
            self.assertEqual(fetch.call_count, 3)
            self.assertFalse(receipt['recovery_eligible'])

    def test_foreign_discovery_receipt_cannot_clear_repair_blocker(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [checked_alpha()])
            current = hashlib.sha256((root / 'all_alphas.jsonl').read_bytes()).hexdigest()
            values = {
                'scout_seed/scout_seed_import.json': {'target_run_id': root.name, 'imported_artifacts': [
                    {'name': 'all_alphas.jsonl', 'sha256': 'old'}]},
                'batch_generation/discovery_execution.json': {'run_id': 'foreign', 'status': 'completed',
                    'input_sha256': 'old', 'output_sha256': 'middle'},
                'repair/repair_execution.json': {'run_id': root.name, 'status': 'paused',
                    'recovery_eligible': True, 'input_sha256': 'middle', 'last_sha256': current}}
            for name, row in values.items():
                path = root / 'stages' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(row))
            result = advance_post_schedule_stage(root, 'repair')
            self.assertEqual(result['status'], 'paused')
            self.assertIn('import receipt', result['blocker'])

    def test_still_pending_is_rechecked_boundedly_instead_of_cached_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [checked_alpha('qualified', hard_pass=False, pending=['SELF_CORRELATION'])])
            fetch = Mock(side_effect=[CheckSummary('parent1', False, [], [], [CheckItem('SELF_CORRELATION', 'PENDING')], {}),
                                      CheckSummary('parent1', True, [], [], [], {})])
            with patch('wqb.pending_check_recovery.CHECK_PENDING_RETRY_SECONDS', 0, create=True):
                recover_pending_checks(root, fetch)
                recover_pending_checks(root, fetch)
            self.assertEqual(fetch.call_count, 2)

    def test_prepared_publish_is_finalized_even_with_no_remaining_pending_rows(self):
        from wqb.pending_check_recovery import CHECK_RECOVERY_RECEIPT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [checked_alpha('qualified', hard_pass=False, pending=['SELF_CORRELATION'])])
            recover_pending_checks(root, lambda identity: CheckSummary(identity, True, [], [], [], {}))
            path = root / CHECK_RECOVERY_RECEIPT
            receipt = json.loads(path.read_text())
            receipt['status'] = 'prepared'
            path.write_text(json.dumps(receipt))
            advance_post_schedule_stage(root, 'backtest')
            self.assertEqual(json.loads(path.read_text())['status'], 'completed')

    def test_journal_survives_interruption_and_receipt_preserves_provenance(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [checked_alpha('qualified', alpha_id=i, expression_hash=i,
                                  hard_pass=False, pending=['SELF_CORRELATION']) for i in ('a', 'b')]
            write_rows(root, rows)
            original = (root / 'all_alphas.jsonl').read_bytes()
            proof = root / 'stages/scout_seed/scout_seed_import.json'
            proof.parent.mkdir(parents=True)
            proof.write_text(json.dumps({'target_run_id': root.name, 'imported_artifacts': [
                {'name': 'all_alphas.jsonl', 'sha256': hashlib.sha256(original).hexdigest()}]}))
            fetch = Mock(side_effect=[CheckSummary('a', True, [], [], [], {}), RuntimeError('offline')])
            with self.assertRaises(RuntimeError):
                recover_pending_checks(root, fetch)
            self.assertEqual((root / 'all_alphas.jsonl').read_bytes(), original)
            resumed = Mock(return_value=CheckSummary('b', True, [], [], [], {}))
            recover_pending_checks(root, resumed)
            resumed.assert_called_once_with('b')
            self.assertEqual(research_evidence_blocker(root), '')
            recover_pending_checks(root, Mock(side_effect=AssertionError('duplicate check')))
            self.assertEqual(research_evidence_blocker(root), '')

    def test_runtime_429_uses_backtest_cooldown_without_simulation(self):
        import requests
        from wqb.discovery_runtime import DiscoveryRuntimeExecutor
        from wqb.repair_runtime import RepairRateLimited
        from wqb.workflow_driver import _repair_cooldown_result
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [checked_alpha('qualified', hard_pass=False, pending=['SELF_CORRELATION'])])
            response = requests.Response()
            response.status_code = 429
            response.headers['Retry-After'] = '60'
            error = requests.HTTPError(response=response)
            with patch('wqb.discovery_runtime.check_submission_allowed'), patch('wqb.cli.build_client'), \
                    patch('wqb.cli.fetch_check_summary', side_effect=error):
                with self.assertRaises(RepairRateLimited):
                    DiscoveryRuntimeExecutor({}).recover_checks(root)
            result = _repair_cooldown_result(root, {'current_stage': 'backtest', 'status': 'paused'},
                                            '2026-10-11T18:15:00+00:00')
            self.assertEqual(result['next_action'], 'rate-limit-wait')
            self.assertTrue(result['source_bridge']['metadata']['retry_at'])

    def test_baseline_failure_still_never_calls_expensive_checks(self):
        client = Mock()
        client.get_json.return_value = {'is': {'checks': [
            {'name': 'LOW_SHARPE', 'result': 'FAIL'}, {'name': 'LOW_FITNESS', 'result': 'PASS'},
            {'name': 'POWER_POOL_CORRELATION', 'result': 'PENDING'}]}}
        self.assertFalse(fetch_check_summary(client, 'a').hard_pass)
        client.get_json.assert_called_once_with('/alphas/a')

    def test_activity_checks_do_not_prevent_final_check_after_baseline_pass(self):
        client = Mock()
        checks = [{'name': n, 'result': 'PASS'} for n in ('LOW_SHARPE', 'LOW_FITNESS')]
        checks += [{'name': n, 'result': 'PENDING'} for n in ('POWER_POOL_CORRELATION', 'MATCHES_THEMES')]
        client.get_json.side_effect = [{'is': {'checks': checks}}, {'is': {'checks': [
            {'name': x['name'], 'result': 'PASS'} for x in checks]}}]
        summary = fetch_check_summary(client, 'a')
        self.assertTrue(summary.hard_pass)
        self.assertEqual(client.get_json.call_count, 2)

    def test_backtest_recovers_only_pending_identity_and_restart_reuses_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending = checked_alpha('qualified', hard_pass=False, pending=['POWER_POOL_CORRELATION'])
            weak = checked_alpha('weak', alpha_id='weak', expression_hash='weak-hash')
            write_rows(root, [pending, weak])
            executor = Mock()
            executor.recover_checks.side_effect = lambda run: write_rows(run, [checked_alpha('qualified'), weak])
            result = advance_post_schedule_stage(root, 'backtest', discovery_executor=executor)
            self.assertEqual(result['status'], 'completed')
            executor.recover_checks.assert_called_once()
            advance_post_schedule_stage(root, 'backtest', discovery_executor=executor)
            executor.recover_checks.assert_called_once()

    def test_pending_message_does_not_claim_existing_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [checked_alpha('qualified', hard_pass=False, pending=['NO_CHECKS'])])
            result = advance_post_schedule_stage(root, 'backtest')
            self.assertIn('pending', result['blocker'])
            self.assertNotIn('results required', result['blocker'])
