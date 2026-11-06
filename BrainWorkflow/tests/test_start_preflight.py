import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wqb.run_readiness import ReadinessIssue, ReadinessReport


class StartPreflightTests(unittest.TestCase):
    def test_paired_readiness_replaces_only_verified_legacy_reader_incompatibility(self):
        from wqb.run_readiness import resolve_operational_readiness
        from tests.test_hypothesis_selection import paired_selection_fixture
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, _ = paired_selection_fixture(Path(tmp))
            issue = ReadinessIssue('block', 'v2_hypothesis_unexecutable',
                'source-backed resource contract requires approved operational evidence context')
            bad = ReadinessReport('research', 'now', False, True, [issue])
            self.assertTrue(resolve_operational_readiness(bad, snapshot).passed)
            for extra in (ReadinessIssue('block', 'stale', 'stale source'),
                          ReadinessIssue('block', 'v2_hypothesis_unexecutable', 'missing operator definition')):
                report = ReadinessReport('research', 'now', False, True, [issue, extra])
                self.assertTrue(resolve_operational_readiness(report, snapshot).blocked)
            empty = ReadinessReport('research', 'now', False, True, [])
            self.assertEqual(resolve_operational_readiness(empty, snapshot), empty)

    def test_paired_preflight_validates_snapshot_before_accepting_legacy_override(self):
        from wqb.start_preflight import prepare_start
        from tests.test_hypothesis_selection import paired_selection_fixture
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, _ = paired_selection_fixture(root)
            issue = ReadinessIssue('block', 'v2_hypothesis_unexecutable',
                'source-backed resource contract requires approved operational evidence context')
            bad = ReadinessReport('research', 'now', False, True, [issue])
            with patch('wqb.start_preflight.evaluate_run_readiness', return_value=bad), patch(
                    'wqb.workflow_stage_adapters.create_start_snapshot', return_value=snapshot) as freeze, patch(
                    'wqb.start_preflight.compile_local_knowledge') as compile_local:
                receipt = prepare_start(root / 'knowledge', root / 'runs', snapshot['selected_scope'], False,
                    research_policy=dict(paired_scout=True), selected_option_id='option-1')
            self.assertTrue(receipt['passed'])
            self.assertTrue(receipt['paired_context_sha256'])
            self.assertFalse(receipt['online_refresh_authorized'])
            compile_local.assert_not_called()
            self.assertEqual(freeze.call_args.kwargs['research_policy'], dict(paired_scout=True))

    def test_ready_knowledge_skips_compilation_and_network(self):
        """Input: ready local scope. Output: assertions. Healthy Start does not recompile the vault."""
        from wqb.start_preflight import prepare_start
        good = ReadinessReport('research', 'now', True, False, [])
        with tempfile.TemporaryDirectory() as tmp, patch('wqb.start_preflight.evaluate_run_readiness', return_value=good), \
                patch('wqb.start_preflight.compile_local_knowledge') as compile_local:
            result = prepare_start(Path(tmp) / 'knowledge', Path(tmp) / 'runs',
                                   {'region': 'USA', 'delay': 1, 'universe': 'TOP3000'}, True)
            compile_local.assert_not_called()
            self.assertTrue(Path(result['receipt_path']).is_file())
            self.assertTrue(result['passed'])

    def test_local_repair_runs_once_then_rechecks_without_network(self):
        """Input: initially missing compiled resource. Output: assertions. Prepare locally before any mission creation."""
        from wqb.start_preflight import prepare_start
        scope = {'region': 'USA', 'delay': 1, 'universe': 'TOP3000'}
        bad = ReadinessReport('research', 'now', False, True, [ReadinessIssue('block', 'missing', 'Missing ledger', 'machine/data_ledger.jsonl')])
        good = ReadinessReport('research', 'now', True, False, [])
        with tempfile.TemporaryDirectory() as tmp, patch('wqb.start_preflight.evaluate_run_readiness', side_effect=[bad, good]), \
                patch('wqb.start_preflight.compile_local_knowledge', return_value={'status': 'completed'}) as compile_local:
            result = prepare_start(Path(tmp) / 'knowledge', Path(tmp) / 'runs', scope, True)
            self.assertTrue(result['passed'])
            compile_local.assert_called_once()
            self.assertFalse((Path(tmp) / 'runs/active_run.json').exists())

    def test_stale_raw_remains_blocked_with_exact_paths_no_mission(self):
        """Input: stale external facts. Output: assertions. Compilation is not platform renewal or discovery permission."""
        from wqb.start_preflight import prepare_start
        bad = ReadinessReport('research', 'now', False, True, [ReadinessIssue('block', 'stale', 'Old operators', 'raw/platform/operators.md', 'Explicit refresh required')])
        with tempfile.TemporaryDirectory() as tmp, patch('wqb.start_preflight.evaluate_run_readiness', return_value=bad), \
                patch('wqb.start_preflight.compile_local_knowledge'):
            result = prepare_start(Path(tmp) / 'knowledge', Path(tmp) / 'runs', {'region': 'USA', 'delay': 1, 'universe': 'TOP3000'}, True)
            self.assertFalse(result['passed'])
            self.assertEqual(result['issues'][0]['path'], 'raw/platform/operators.md')
            self.assertFalse(result['online_refresh_authorized'])
            self.assertEqual(list((Path(tmp) / 'runs').glob('*/run_state.json')), [])
