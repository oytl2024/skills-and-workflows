"""Tree runtime drives existing source transport, never a second simulator."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from wqb import tree_runtime as subject


class TreeRuntimeTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: isolated source-certified tree fixture, not a live run."""
        from tests.test_research_tree import ResearchTreeTests
        self.fixture = ResearchTreeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.run = self.fixture.run
        self.fixture.freeze()
        self.config = dict(region='USA', delay=1, universe='TOP3000', instrument_type='EQUITY')

    def source(self, config, metadata):
        """Input: authenticated executor config/metadata dicts. Output: local fake source receipt."""
        source = self.run.parent / ('source-' + metadata['tree_plan_id'][:10])
        source.mkdir(exist_ok=True)
        (source / 'run_meta.jsonl').write_text(json.dumps(dict(
            ai_plan_receipt=config['ai_plan_receipt'], research_round_id=config['research_round_id'])) + '\n')
        return dict(run_dir=str(source), status='offline')

    def test_offline_authority_never_dispatches_and_restart_never_resubmits(self):
        runner = Mock(side_effect=self.source)
        first = subject.continue_tree(self.run, self.config, '2026-10-23T00:00:00Z',
                                      source_batch_runner=runner)
        self.assertEqual(first['next_action'], 'enable-live-api-required')
        runner.assert_not_called()
        subject.continue_tree(self.run, self.config, '2026-10-23T00:00:00Z',
                              enable_live_api=True, source_batch_runner=runner)
        self.assertEqual(runner.call_count, 1)
        subject.continue_tree(self.run, self.config, '2026-10-23T00:00:01Z',
                              enable_live_api=True, source_batch_runner=runner)
        self.assertEqual(runner.call_count, 1)

    def test_stop_wins_over_dispatch(self):
        from wqb.runtime_control import _write
        control = json.loads((self.run / 'runtime_control.json').read_text())
        _write(self.run / 'runtime_control.json', dict(control, desired_state='paused'))
        runner = Mock()
        result = subject.continue_tree(self.run, self.config, '2026-10-23T00:00:00Z',
                                      enable_live_api=True, source_batch_runner=runner)
        self.assertEqual(result['next_action'], 'runtime-paused')
        runner.assert_not_called()

    def test_parallel_source_directories_cannot_collide_in_same_second(self):
        from wqb.cli import make_run_dir
        config = dict(run_root=str(self.run.parent), active_workflow_run_dir=str(self.run))
        with patch('wqb.research_seed_stage.preplanned_research_enabled', return_value=True):
            one, two = make_run_dir(config), make_run_dir(config)
        self.assertNotEqual(one, two)
        self.assertEqual(one.parent, self.run.parent)

    def test_early_qualified_candidate_cannot_hide_inflight_sibling(self):
        from wqb.source_bridge import _decision_for_source
        source = self.run.parent / 'partial-source'
        source.mkdir()
        (source / 'candidates.csv').write_text('alpha_id,expression_hash\na1,h1\n')
        (source / 'simulation_events.jsonl').write_text(json.dumps(dict(
            event='SUBMITTED', progress_url='https://example.invalid/progress/2', expression_hash='h2'))+'\n')
        self.assertEqual(_decision_for_source(source, '2026-10-23T00:00:00Z').action, 'import_existing')
        decision = _decision_for_source(source, '2026-10-23T00:00:00Z', require_complete_batch=True)
        self.assertEqual(decision.action, 'complete_in_flight')

    def test_first_pair_is_not_published_before_descendants_finish(self):
        result = subject.continue_tree(self.run, self.config, '2026-10-23T00:00:00Z',
                                      enable_live_api=True, source_batch_runner=self.source)
        source = Path(result['tree']['executor_result']['run_dir'])
        rows = [self.fixture.checked(sharpe=1.5), self.fixture.checked(arm='treatment', sharpe=1.6)]
        (source / 'all_alphas.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        with patch('wqb.tree_runtime._decision_for_source', return_value=None):
            result = subject.continue_tree(self.run, self.config, '2026-10-23T00:00:01Z')
        self.assertEqual(result['next_action'], 'enable-live-api-required')
        self.assertFalse((self.run / 'all_alphas.jsonl').exists())

    def test_orchestrator_version_route_does_not_import_first_source_or_replan(self):
        from wqb.workflow_auto_continue import auto_continue_workflow
        state = dict(active=True, status='paused', current_stage='scout_seed',
                     run_dir=str(self.run), pause_reason='checked research results required')
        with patch('wqb.workflow_auto_continue.WorkflowOrchestrator') as constructor, \
                patch('wqb.research_rounds.reconcile_research_budget_wait', return_value={'status':'unchanged'}), \
                patch('wqb.research_seed_stage.preplanned_research_enabled', return_value=True), \
                patch('wqb.tree_runtime.continue_tree', return_value={'next_action':'workflow-auto-continue'}) as tree, \
                patch('wqb.workflow_auto_continue.inspect_scout_seed_source_bridge') as legacy:
            constructor.return_value.status.return_value = state
            result = auto_continue_workflow(Mock(), {}, '2026-10-23T00:00:00Z')
            self.assertEqual(result['current_stage'], 'scout_seed')
            tree.assert_called_once()
            legacy.assert_not_called()
            constructor.return_value.resume.assert_not_called()

    def test_missing_actual_dates_are_not_filled_from_plan(self):
        row = deepcopy(self.fixture.checked())
        row.pop('measurement_period')
        row.pop('test_period')
        normalized = subject.measured_row(row, self.run.name)
        self.assertNotIn('measurement_period', normalized)
        row['metrics'].update(startDate='2020-01-01', endDate='2025-12-31')
        normalized = subject.measured_row(row, self.run.name)
        self.assertEqual(normalized['measurement_period'], self.fixture.period)

    def test_two_levels_publish_all_measured_rows_only_after_tree_finishes(self):
        from wqb.cli import simulation_identity_hash
        def complete_source(config, metadata):
            """Input: exact tree candidates. Output: fake source containing real-shaped measurements."""
            result = self.source(config, metadata)
            rows = []
            for candidate in config['scheduled_hypotheses']:
                identity = simulation_identity_hash(candidate['bound_expression'], candidate['settings'])
                match = next((name, arm) for name in ('root', 'left', 'right')
                             for arm, value in self.fixture.identities(name).items() if value == identity)
                rows.append(self.fixture.checked(*match, sharpe=1.6, fitness=.8))
            Path(result['run_dir'], 'all_alphas.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            return result
        # Source decision classification is tested separately; no platform is used.
        with patch('wqb.tree_runtime._decision_for_source', return_value=None):
            first = subject.continue_tree(self.run, self.config, '2026-10-23T00:00:00Z',
                enable_live_api=True, source_batch_runner=complete_source)
            self.assertFalse(first.get('tree_complete'))
            second = subject.continue_tree(self.run, self.config, '2026-10-23T00:00:01Z',
                enable_live_api=True, source_batch_runner=complete_source)
            self.assertFalse(second.get('tree_complete'))
            final = subject.continue_tree(self.run, self.config, '2026-10-23T00:00:02Z')
        self.assertTrue(final['tree_complete'])
        rows = subject.checked_research_rows(self.run)
        self.assertEqual(len(rows), 4)
        subject.verify_tree_results(self.run)


if __name__ == '__main__':
    unittest.main()
