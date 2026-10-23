"""Offline composition -> real multisim transport boundary -> measured Seed acceptance."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class PreplannedResearchAcceptanceTests(unittest.TestCase):
    def test_daily_rollover_releases_frozen_pair_without_refund_or_model_call(self):
        """Input: none. Output: None; next day funds the same pair while retaining lifetime usage and authority."""
        from tests.test_preplanned_start import PreplannedStartTests
        from wqb.daily_simulation_budget import charge_daily_budget, read_daily_budget
        from wqb.research_group_driver import initialize_group_runtime
        from wqb.research_group import resume_group, read_group
        from wqb.runtime_control import request_runtime_state
        from wqb.tree_runtime import continue_tree
        fixture = PreplannedStartTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.paths.project_root = fixture.root
        fixture.paths.workflow_root = Path(__file__).resolve().parents[1]
        fixture.authority['enable_live_api'] = True
        prepared = fixture.prepare()
        group = initialize_group_runtime(fixture.paths, prepared['group'])
        run = fixture.paths.run_root / group['lanes'][0]['run_id']
        request_runtime_state(run, 'running')
        group = resume_group(Path(group['group_dir']), group['request_revision'])
        charge_daily_budget(run, 3999, 'fixture-history')
        waiting = continue_tree(run, fixture.config, None)
        self.assertEqual(waiting['next_action'], 'daily-budget-wait', waiting)
        reset = waiting['daily_simulation_budget']['next_reset_at']
        handoffs = []
        def execute(config, metadata):
            """Input: frozen source config/metadata. Output: fake acknowledgement; no POST or worker."""
            handoffs.append(config)
            return dict(status='fixture-handoff-only')
        with patch('wqb.daily_simulation_budget.read_daily_budget',
                   side_effect=lambda owner, now=None: read_daily_budget(owner, now or reset)):
            resumed = continue_tree(run, fixture.config, reset, enable_live_api=True, source_batch_runner=execute)
        self.assertEqual(resumed['next_action'], 'workflow-auto-continue', resumed)
        self.assertEqual(len(handoffs), 1)
        self.assertEqual(len(handoffs[0]['scheduled_hypotheses']), 2)
        self.assertEqual(read_daily_budget(run, reset)['remaining'], 4000)
        self.assertEqual(read_daily_budget(run, reset)['lifetime_attempts'], 3999)
        self.assertEqual(fixture.runner.call_count, 1)
        self.assertEqual(read_group(Path(group['group_dir']))['authority'], group['authority'])

    def test_incomplete_pair_daily_wait_is_driver_compatible_and_stop_interrupts(self):
        from tests.test_preplanned_start import PreplannedStartTests
        from wqb.daily_simulation_budget import charge_daily_budget
        from wqb.research_group_driver import initialize_group_runtime
        from wqb.research_group import resume_group, stop_group
        from wqb.runtime_control import request_runtime_state
        from wqb.tree_runtime import continue_tree
        from wqb.workflow_driver import run_workflow_driver
        fixture = PreplannedStartTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.paths.project_root = fixture.root
        fixture.paths.workflow_root = Path(__file__).resolve().parents[1]
        fixture.authority['enable_live_api'] = True
        prepared = fixture.prepare()
        self.assertEqual(prepared['status'], 'completed', prepared)
        group = initialize_group_runtime(fixture.paths, prepared['group'])
        run = fixture.paths.run_root / group['lanes'][0]['run_id']
        request_runtime_state(run, 'running')
        group = resume_group(Path(group['group_dir']), group['request_revision'])
        charge_daily_budget(run, 3999, 'fixture-history')
        initial = dict(active=True, run_dir=str(run), status='running', current_stage='scout_seed')
        def step():
            """Input: none. Output: actual tree wait adapted to existing driver envelope, no fake transport."""
            return {**initial, **continue_tree(run, fixture.config, '2026-10-23T00:00:00Z')}
        waiting = step()
        self.assertEqual(waiting['next_action'], 'daily-budget-wait', waiting)
        self.assertEqual(waiting['daily_simulation_budget']['remaining'], 1)
        self.assertEqual(waiting['required_pair_count'], 2)
        def stop(_seconds):
            """Input: wait slice float. Output: durable group Stop without sleeping or advancing authority."""
            stop_group(Path(group['group_dir']), group['request_revision'])
        result = run_workflow_driver(fixture.paths, dict(bound_group_lane=str(run)), step=step,
            status_reader=lambda: initial, now_func=lambda: '2026-10-23T00:00:00Z', sleep_func=stop)
        self.assertEqual(result['runtime_status'], 'paused')

    def test_report_scope_is_comparable_without_fabricating_capture_timestamp(self):
        from tests.test_preplanned_start import PreplannedStartTests
        from wqb.research_tree import _load, _measurements
        from wqb.tree_runtime import measured_row
        from wqb.experiment_tree import route_pair
        fixture = PreplannedStartTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        prepared = fixture.prepare()
        self.assertEqual(prepared['status'], 'completed', prepared)
        run = fixture.paths.run_root / prepared['group']['lanes'][0]['run_id']
        tree, _ = _load(run)
        node = tree['tree']['nodes'][0]
        rows = []
        for expected in node['expected'].values():
            row = dict(status='CHECKED', alpha_id=expected['simulation_identity'][:12],
                expression_hash=expected['simulation_identity'], expression=expected['expression'],
                settings=expected['settings'], hard_pass=False, failed=['LOW_FITNESS'], pending=[],
                metrics=dict(sharpe=1.6, fitness=.8, returns=.1, turnover=.2,
                             startDate='2020-01-01', endDate='2025-01-01'))
            rows.append(measured_row(row, run.name))
        self.assertNotIn('as_of', rows[0]['scope'])
        self.assertEqual(route_pair(node, _measurements(rows))['status'], 'finished')

    def test_two_lanes_use_frozen_plans_shared_accounting_and_no_late_model(self):
        from tests.test_preplanned_start import PreplannedStartTests
        from tests.test_group_runtime_integration import transport
        from wqb import tree_runtime
        from wqb.cli import simulation_identity_hash
        from wqb.daily_simulation_budget import read_daily_budget
        from wqb.research_group import resume_group, stop_group
        from wqb.research_group_driver import initialize_group_runtime
        from wqb.research_seed_stage import prepare_seed_selection
        from wqb.runtime_control import CONTROL_ENV, request_runtime_state
        from wqb.simulator import submit_multisimulation
        fixture = PreplannedStartTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.add_lane(1)
        fixture.config['parallel_workflows'] = 2
        fixture.authority['enable_live_api'] = True
        fixture.paths.project_root = fixture.root
        fixture.paths.workflow_root = Path(__file__).resolve().parents[1]
        fixture.runner.side_effect = fixture.answer_for_brief
        prepared = fixture.prepare()
        self.assertEqual(prepared['status'], 'completed', prepared)
        self.assertEqual(fixture.runner.call_count, 2)
        group = initialize_group_runtime(fixture.paths, prepared['group'])
        for lane in group['lanes']:
            request_runtime_state(fixture.paths.run_root / lane['run_id'], 'running')
        group = resume_group(Path(group['group_dir']), group['request_revision'])
        attempts = []
        def source_runner(config, metadata):
            """Input: exact frozen tree candidates. Output: fake-source result after real bounded POST accounting."""
            run = Path(config['active_workflow_run_dir'])
            candidates = config['scheduled_hypotheses']
            client, session = transport()
            payloads = [dict(type='REGULAR', regular=row['bound_expression'], settings=row['settings']) for row in candidates]
            with patch.dict(os.environ, {CONTROL_ENV: str(run)}):
                submit_multisimulation(client, payloads)
            self.assertEqual(session.request.call_count, 1)
            source = run.parent / ('fixture-source-' + run.name)
            source.mkdir()
            (source / 'run_meta.jsonl').write_text(json.dumps(dict(ai_plan_receipt=config['ai_plan_receipt'],
                research_round_id=config['research_round_id']))+'\n')
            rows = []
            for index, candidate in enumerate(candidates):
                identity = simulation_identity_hash(candidate['bound_expression'], candidate['settings'])
                rows.append(dict(status='CHECKED', alpha_id='fixture-' + identity[:12], expression_hash=identity,
                    expression=candidate['bound_expression'], settings=deepcopy(candidate['settings']),
                    hard_pass=False, failed=['LOW_FITNESS'], pending=['SELF_CORRELATION', 'PROD_CORRELATION'],
                    metrics=dict(sharpe=1.5 + index*.1, fitness=.8 + index*.1, returns=.1, turnover=.2,
                                 startDate='2020-01-01', endDate='2025-01-01')))
            (source / 'all_alphas.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            (source / 'simulation_events.jsonl').write_text(''.join(json.dumps(dict(
                event='CHECKED', expression_hash=row['expression_hash']))+'\n' for row in rows))
            attempts.extend(row['expression_hash'] for row in rows)
            return dict(run_dir=str(source), status='completed')
        for lane in group['lanes']:
            run = fixture.paths.run_root / lane['run_id']
            first = tree_runtime.continue_tree(run, fixture.config, '2026-10-23T00:00:00Z',
                enable_live_api=True, source_batch_runner=source_runner)
            self.assertEqual(first['next_action'], 'workflow-auto-continue', first)
            final = tree_runtime.continue_tree(run, fixture.config, '2026-10-23T00:00:01Z')
            self.assertTrue(final.get('tree_complete'), final)
            tree_runtime.verify_tree_results(run)
            selected = prepare_seed_selection(run, tree_runtime.checked_research_rows(run))
            self.assertTrue(selected['selected'], selected)
            self.assertFalse(selected['submission_qualified'])
        self.assertEqual(len(attempts), 4)
        self.assertEqual(len(set(attempts)), 4)
        self.assertEqual(read_daily_budget(run)['used'], 4)
        self.assertEqual(fixture.runner.call_count, 2)
        stop_group(Path(group['group_dir']), group['request_revision'])
        stopped = tree_runtime.continue_tree(run, fixture.config, '2026-10-23T00:00:02Z',
            enable_live_api=True, source_batch_runner=lambda *_: self.fail('Stop must win'))
        self.assertEqual(stopped['next_action'], 'runtime-paused')


if __name__ == '__main__':
    unittest.main()
