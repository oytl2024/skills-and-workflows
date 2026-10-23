"""Offline adapter contracts; all evidence and command effects are fictional."""
import copy
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wqb import console_api as api
from wqb.research_group import create_group


def save(path, value):
    """Input: Path and JSON value. Output: None; write isolated fixture evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def projection_fixture(legacy=False):
    """Input: legacy bool. Output: dict; real adapter snapshot over isolated shared contract records."""
    case = ConsoleApiTests()
    case.setUp()
    try:
        fixture = json.loads((Path(__file__).parents[1] / 'frontend/tests/projection.contract.json').read_text())
        for path, key in [('runtime/experiment_tree.json', 'tree'), ('runtime/tree_execution.json', 'execution'),
                          ('stages/scout_seed/seed_selection.json', 'selection'),
                          ('stages/repair/repair_execution.json', 'repair')]:
            if not legacy or key == 'repair':
                save(case.run / path, fixture[key])
        if legacy:
            save(case.run / 'stages/batch_generation/seed.json', {'parent': fixture['selection']['seed_rows'][0]})
        (case.run / 'all_alphas.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in fixture['rows']), encoding='utf-8')
        return case.snapshot()
    finally:
        case.doCleanups()


class ConsoleApiTests(unittest.TestCase):
    def test_tree_source_progress_visible_before_batch_returns_without_root_results(self):
        """Input: real consumed tree fixture. Output: assertions; project in-flight source without legacy binding."""
        from tests.test_research_tree import ResearchTreeTests
        from wqb.tree_runtime import continue_tree
        case = ResearchTreeTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        run = case.run
        case.manifest['start_snapshot']['research_policy']['preplanned_tree_version'] = 1
        save(run / 'run_manifest.json', case.manifest)
        from wqb.exploration_eligibility import certify_exploration_resources, build_exploration_snapshot
        cert = certify_exploration_resources(run, case.vault, case.compiler_resources, case.scope)
        snapshot = build_exploration_snapshot(list(case.receipts.values()),
            resource_certificates=[cert] * len(case.receipts))
        case.manifest['start_snapshot'].update(snapshot)
        save(run / 'run_manifest.json', case.manifest)
        case.freeze()
        save(run / 'run_state.json', {'run_id': run.name})
        # A stale, invalid legacy path must not mask the new tree source.
        save(run / 'stages/scout_seed/source_bridge_binding.json', {'source_run_dir': 'Z:/legacy-missing'})
        seen = []

        def batch(config, metadata):
            """Input: actual frozen batch args. Output: fake result; inspect progress inside synchronous callback."""
            source = run.parent / 'source-current'
            source.mkdir()
            (source / 'run_meta.jsonl').write_text(json.dumps(dict(ai_plan_receipt=config['ai_plan_receipt'],
                research_round_id=config['research_round_id'])) + '\n', encoding='utf-8')
            checked = case.checked()
            planned = {k: checked[k] for k in ('expression_hash', 'expression', 'settings')}
            (source / 'planned_candidates.jsonl').write_text(json.dumps(planned) + '\n', encoding='utf-8')
            event = dict(planned, event='SUBMITTED', alpha_id='in-flight-alpha')
            (source / 'simulation_events.jsonl').write_text(json.dumps(event) + '\n', encoding='utf-8')
            unrelated = run.parent / 'unrelated-source'
            unrelated.mkdir()
            (unrelated / 'run_meta.jsonl').write_text(json.dumps(dict(ai_plan_receipt='unconsumed-plan',
                research_round_id=config['research_round_id'])) + '\n', encoding='utf-8')
            (unrelated / 'simulation_events.jsonl').write_text(json.dumps(
                dict(event, alpha_id='not-owned', metrics={'sharpe': 99})) + '\n', encoding='utf-8')
            self.assertFalse((run / 'all_alphas.jsonl').exists())
            lane = api._lane(run, progress={'source_run_dir': 'Z:/legacy-missing', 'rows': []})
            root = next(n for n in lane['nodes'] if n['node_id'] == 'root')
            self.assertEqual(root['arms']['baseline']['state'], 'running')
            self.assertEqual(root['arms']['baseline']['alpha_id'], 'in-flight-alpha')
            self.assertEqual(root['arms']['baseline']['metrics'], {})
            duplicate = run.parent / 'duplicate-source'
            duplicate.mkdir()
            (duplicate / 'run_meta.jsonl').write_bytes((source / 'run_meta.jsonl').read_bytes())
            with self.assertRaisesRegex(ValueError, 'multiple source runs'):
                api._lane(run)
            (duplicate / 'run_meta.jsonl').unlink()
            seen.append(root)
            return dict(run_dir=str(source))

        continue_tree(run, dict(region='USA', delay=1, universe='TOP3000'), '2026-10-23T00:00:00Z',
                      enable_live_api=True, source_batch_runner=batch)
        self.assertEqual(len(seen), 1)

    def test_actual_research_engine_freeze_and_execution_are_projected(self):
        from tests.test_research_tree import ResearchTreeTests
        case = ResearchTreeTests()
        case.setUp()
        try:
            case.freeze()
            checked = case.checked()
            case.advance([checked])
            save(case.run / 'run_state.json', {'run_id': case.run.name})
            lane = api._lane(case.run)
            root = next(node for node in lane['nodes'] if node['node_id'] == 'root')
            self.assertEqual(root['layer'], 1)
            self.assertEqual(root['arms']['baseline']['alpha_id'], checked['alpha_id'])
            self.assertEqual(root['arms']['baseline']['metrics'], checked['metrics'])
            self.assertEqual(root['arms']['baseline']['expression'], checked['expression'])
            self.assertEqual(root['arms']['baseline']['settings'], checked['settings'])
            self.assertIsNone(root['arms']['treatment']['alpha_id'])
        finally:
            case.doCleanups()

    def test_unknown_legacy_strings_and_null_layer_remain_parseable(self):
        self.state['active_workflow'].update(status=None, current_stage=None)
        self.state['strategy_progress'] = {'rows': [{'key': 'legacy', 'state': None, 'layer': None}]}
        lane, = self.snapshot()['lanes']
        self.assertEqual((lane['status'], lane['stage'], lane['nodes'][0]['state']), ('unknown', 'unknown', 'unknown'))
        self.assertIsNone(lane['nodes'][0]['layer'])

    def test_arbitrary_root_seed_json_does_not_select_research_cores(self):
        save(self.run / 'seed_selection.json', {'selected': [{'alpha_id': 'not-authoritative'}]})
        self.assertEqual(self.snapshot()['lanes'][0]['seeds'], [])

    def test_selected_seed_missing_exact_actual_identity_fails_closed(self):
        save(self.run / 'stages/scout_seed/seed_selection.json', {
            'selected': [{'identity': {'expression_hash': 'hash', 'alpha_id': 'a'}, 'score': 9}],
            'seed_rows': [{'expression_hash': 'hash', 'alpha_id': 'other', 'metrics': {'sharpe': 10}}]})
        self.assertIn('Seed measured identity', self.snapshot()['blocker'])

    def test_tree_overlay_must_belong_to_same_run_and_digest(self):
        save(self.run / 'runtime/experiment_tree.json', {'schema_version': 1, 'tree_digest': 'one', 'nodes': []})
        save(self.run / 'runtime/tree_execution.json', {'run_id': self.run.name, 'tree_digest': 'other'})
        self.assertIn('tree execution identity mismatch', self.snapshot()['blocker'])

    def test_runtime_tree_precedes_legacy_tree_and_uses_checked_decisions(self):
        config = {'simulation_identity': 'hash', 'expression': 'rank(x)', 'settings': {'decay': 5}}
        save(self.run / 'runtime/experiment_tree.json', {'schema_version': 1, 'tree_digest': 'one',
            'tree': {'nodes': [{'node_id': 'new', 'expected': {'baseline': config}}]}})
        save(self.run / 'experiment_tree.json', {'schema_version': 1, 'nodes': [{'node_id': 'old'}]})
        checked = dict(config, expression_hash='hash', status='CHECKED', alpha_id='actual', metrics={'sharpe': 0})
        save(self.run / 'runtime/research_plans/tree-decision-fixture.json', {'tree_digest': 'one', 'checked_rows': [checked]})
        first, = self.snapshot()['lanes'][0]['nodes']
        self.assertEqual(first['node_id'], 'new')
        self.assertEqual(first['arms']['baseline']['metrics'], {'sharpe': 0})
        save(self.run / 'runtime/research_plans/tree-decision-other.json', {
            'tree_digest': 'one', 'checked_rows': [dict(checked, metrics={'sharpe': 9})]})
        second, = self.snapshot()['lanes'][0]['nodes']
        self.assertEqual(second['arms']['baseline']['state'], 'conflict')
        self.assertEqual(second['arms']['baseline']['metrics'], {})
        self.assertIsNone(second['arms']['baseline']['alpha_id'])
        self.assertEqual(second['arms']['baseline']['node_id'], first['arms']['baseline']['node_id'])

    def test_repair_trace_child_and_signal_score_never_use_parent_measurement(self):
        variant = {'expression_hash': 'child', 'expression': 'rank(x)', 'settings': {'decay': 8}}
        attempt = {'parent_alpha_id': 'parent', 'phase': 'waiting', 'plan': {'variants': [variant]},
                   'experiment_trace': {'baseline': {'alpha_id': 'parent', 'metrics': {'sharpe': 99}, 'signal_score': 99}}}
        save(self.run / 'stages/repair/repair_execution.json', {'attempts': [attempt]})
        pending, = self.snapshot()['lanes'][0]['repair']
        self.assertIsNone(pending['alpha_id'])
        self.assertIsNone(pending['score'])
        attempt['experiment_trace'].update(measured_child=dict(variant, alpha_id='child-id', signal_score=.4),
                                           reasons=['objective_not_improved'])
        save(self.run / 'stages/repair/repair_execution.json', {'attempts': [attempt]})
        measured, = self.snapshot()['lanes'][0]['repair']
        self.assertEqual(measured['node_id'], pending['node_id'])
        self.assertEqual(measured['score'], .4)
        self.assertEqual(measured['alpha_id'], 'child-id')
        self.assertIn('objective_not_improved', measured['reason'])

    def test_repair_conflicting_child_does_not_supply_fake_measurements(self):
        variant = {'expression_hash': 'child', 'expression': 'rank(x)', 'settings': {'decay': 8}}
        save(self.run / 'stages/repair/repair_execution.json', {'attempts': [{
            'plan': {'variants': [variant]}, 'children': [dict(variant, expression='rank(y)', alpha_id='wrong', metrics={'sharpe': 9})]}]})
        node, = self.snapshot()['lanes'][0]['repair']
        self.assertEqual(node['expression'], 'rank(x)')
        self.assertEqual(node['state'], 'conflict')
        self.assertIsNone(node['alpha_id'])
        self.assertEqual(node['metrics'], {})

    def test_shared_projection_contract_uses_actual_records(self):
        result = projection_fixture()
        self.assertFalse(result['blocker'])
        lane, = result['lanes']
        pair, = lane['nodes']
        self.assertEqual(pair['state'], 'waiting')
        self.assertIsNone(pair['layer'])
        baseline, treatment = pair['arms']['baseline'], pair['arms']['treatment']
        self.assertEqual(baseline['alpha_id'], 'fixture-baseline')
        self.assertEqual(baseline['metrics']['sharpe'], 1.5)
        self.assertEqual(treatment['expression'], 'rank(ts_mean(fixture_x, 22))')
        self.assertIsNone(treatment['alpha_id'])
        self.assertEqual(treatment['metrics'], {})
        self.assertEqual(lane['seeds'][0]['score'], .75)
        self.assertEqual(lane['seeds'][0]['expression'], 'rank(fixture_x)')
        self.assertEqual(lane['repair'][0]['expression'], 'rank(ts_delta(fixture_x, 5))')
        self.assertEqual(lane['repair'][0]['alpha_id'], 'fixture-repair')
        self.assertEqual(lane['repair'][0]['score'], .81)
        self.assertIsNone(lane['repair'][1]['alpha_id'])
        self.assertIsNone(lane['repair'][1]['score'])

    def setUp(self):
        """Input: none. Output: None; prepare an isolated legacy run and Console state."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runs = Path(self.temp.name) / 'runs'
        self.run = self.runs / 'legacy-run'
        self.run.mkdir(parents=True)
        self.paths = SimpleNamespace(runs_root=self.runs, job_root=self.runs / 'console_jobs')
        self.state = {'active_workflow': {'exists': True, 'run_id': self.run.name,
            'run_dir': str(self.run), 'status': 'paused', 'current_stage': 'scout_seed'},
            'runtime_control': {'desired_state': 'paused', 'request_revision': 'r1'},
            'option_cards': [{'option_id': 'o1', 'title': 'Fictional direction'}]}
        save(self.run / 'run_state.json', self.state['active_workflow'])

    def snapshot(self):
        """Input: none. Output: dict; project current fixture state."""
        return api.project_application(self.paths, self.state, 'epoch', 7)

    def command(self, action='start', command_id='cmd-1'):
        """Input: action/id strings. Output: dict; bind command to observed revision."""
        return {'command_id': command_id, 'action': action,
                'expected_revision': self.snapshot()['request_revision']}

    def submit(self, command, runner):
        """Input: command dict and callable. Output: dict; use injected offline actions."""
        return api.submit_command(self.paths, command, action_runner=runner,
                                  state_reader=lambda: copy.deepcopy(self.state))

    def test_legacy_lane_has_no_invented_evidence_and_no_mutation(self):
        before = copy.deepcopy(self.state)
        result = self.snapshot()
        self.assertEqual((result['schema_version'], result['server_epoch'], result['sequence']), (1, 'epoch', 7))
        lane, = result['lanes']
        self.assertEqual(lane['lane_id'], self.run.name)
        self.assertEqual(lane['status'], 'paused')
        self.assertEqual(lane['nodes'], [])
        self.assertEqual(lane['seeds'], [])
        self.assertTrue(result['allowed_actions']['start'])
        self.assertEqual(self.state, before)
        self.assertFalse((self.runs / 'research_groups').exists())
        self.assertEqual(result['group']['group_id'], 'legacy:' + self.run.name)

    def test_empty_group_and_optional_command_group_identity(self):
        self.state['active_workflow'] = {}
        result = self.snapshot()
        self.assertEqual(result['group'], {'group_id': 'none', 'status': 'unknown', 'desired_state': 'paused'})
        command = self.command() | {'group_id': 'none'}
        self.assertEqual(self.submit(command, lambda *_: {'status': 'accepted'})['status'], 'accepted')
        command = self.command(command_id='foreign-group') | {'group_id': 'legacy:foreign'}
        self.assertEqual(self.submit(command, lambda *_: self.fail('group mismatch'))['status'], 'refused')

    def test_progress_identity_metrics_and_missing_values_remain_distinct(self):
        self.state['strategy_progress'] = {'source_run_dir': str(self.run), 'rows': [
            {'key': 'child-a', 'expression': 'rank(x)', 'status': 'planned'},
            {'key': 'child-b', 'alpha_id': 'real-fixture-id', 'status': 'checked',
             'metrics': {'sharpe': 1.23}, 'settings': {'delay': 1}}]}
        nodes = self.snapshot()['lanes'][0]['nodes']
        self.assertEqual([n['node_id'] for n in nodes], ['child-a', 'child-b'])
        self.assertIsNone(nodes[0]['alpha_id'])
        self.assertEqual(nodes[0]['metrics'], {})
        self.assertEqual(nodes[1]['metrics'], {'sharpe': 1.23})
        self.assertIsNone(nodes[1]['layer'])

    def test_group_pointer_and_membership_verified_without_adoption(self):
        group = create_group(self.runs, [{'run_id': 'a', 'plan_digest': 'a'*64},
                                        {'run_id': 'b', 'plan_digest': 'b'*64}],
                             {'enable_live_api': False, 'max_runtime_seconds': 100, 'max_recoveries': 1})
        save(self.runs / 'active_research_group.json', {'group_id': group['group_id']})
        for run_id in ('a', 'b'):
            save(self.runs / run_id / 'run_state.json', {'run_id': run_id, 'status': 'paused', 'current_stage': 'repair'})
        result = self.snapshot()
        self.assertEqual([r['lane_id'] for r in result['lanes']], ['a', 'b'])
        self.assertEqual(result['group']['group_id'], group['group_id'])
        save(self.runs / 'a/research_group_binding.json', {})
        result = self.snapshot()
        self.assertTrue(result['blocker'])
        self.assertFalse(result['allowed_actions']['start'])
        self.assertEqual(result['lanes'], [])

    def test_unsafe_pointer_is_not_silently_replaced_by_legacy(self):
        save(self.runs / 'active_research_group.json', {'group_id': '../legacy-run'})
        result = self.snapshot()
        self.assertTrue(result['blocker'])
        self.assertEqual(result['lanes'], [])

    def test_group_authority_not_legacy_state_controls_start_and_stop(self):
        from tests.test_research_group_driver import ResearchGroupDriverTests
        from wqb.research_group_driver import initialize_group_runtime
        from wqb.research_group import resume_group
        from wqb.runtime_control import read_runtime_control
        case = ResearchGroupDriverTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        group = case.prepared(2, live=False)
        initialize_group_runtime(case.paths, group)
        paths = SimpleNamespace(runs_root=case.paths.run_root)
        result = api.project_application(paths, {}, 'offline', 1)
        self.assertEqual(result['allowed_actions'], {'start': True, 'stop': True})
        self.assertEqual(result['group']['status'], 'paused')
        resume_group(Path(group['group_dir']), group['request_revision'])
        result = api.project_application(paths, {}, 'offline', 2)
        self.assertEqual(result['group']['status'], 'running')
        self.assertEqual(result['allowed_actions'], {'start': False, 'stop': True})
        self.assertEqual(read_runtime_control(case.paths.run_root / 'lane-0')['desired_state'], 'paused')
        (case.paths.run_root / 'lane-0/runtime/experiment_tree.json').write_text('{', encoding='utf-8')
        result = api.project_application(paths, {}, 'offline', 3)
        self.assertEqual(result['group']['group_id'], group['group_id'])
        self.assertTrue(result['allowed_actions']['stop'])
        self.assertFalse(result['allowed_actions']['start'])
        self.assertTrue(result['request_revision'])
        self.assertTrue(result['blocker'])

    def test_node_details_only_read_existing_safe_artifacts(self):
        row = {'node_id': 'n1', 'parent_id': None, 'layer': 1, 'hypothesis': 'Observed hypothesis',
               'expression': 'rank(x)', 'settings': {'delay': 1}, 'metrics': {'sharpe': .8}}
        save(self.run / 'experiment_tree.json', {'schema_version': 1, 'tree': {'nodes': [row]}})
        result = api.project_node(self.run, 'n1')
        self.assertEqual(result['expression'], 'rank(x)')
        self.assertIsNone(result['alpha_id'])
        self.assertTrue(api.project_node(self.run, '../n1')['blocker'])
        self.assertTrue(api.project_node(self.run, 'absent')['blocker'])

    def test_corrupt_oversize_nonfinite_and_source_escape_become_blockers(self):
        for payload in ('{', '{"metrics": NaN}'):
            (self.run / 'experiment_tree.json').write_text(payload, encoding='utf-8')
            self.assertTrue(self.snapshot()['blocker'])
        with patch.object(api, 'MAX_ARTIFACT_BYTES', 2):
            self.assertTrue(self.snapshot()['blocker'])
        (self.run / 'experiment_tree.json').unlink()
        save(self.run / 'stages/scout_seed/source_bridge_binding.json', {'source_run_dir': str(self.runs.parent)})
        self.assertTrue(self.snapshot()['blocker'])

    def test_seed_and_repair_are_existing_records_not_recomputed_qualification(self):
        save(self.run / 'stages/batch_generation/seed.json', {'parent': {'alpha_id': 'seed-a',
            'expression_hash': 'hash', 'metrics': {'sharpe': 1.7}, 'score': .64}, 'reason': 'Persisted reason'})
        save(self.run / 'stages/repair/repair_execution.json', {'attempts': [
            {'parent_alpha_id': 'seed-a', 'phase': 'waiting', 'score': .6,
             'plan': {'decision': {'hypothesis': 'One change'}}}]})
        lane = self.snapshot()['lanes'][0]
        self.assertEqual(lane['seeds'][0]['score'], .64)
        self.assertEqual(lane['repair'][0]['hypothesis'], 'One change')
        self.assertEqual(lane['repair'][0]['score'], .6)

    def test_duplicate_ack_and_payload_conflict_never_repeat_action(self):
        calls = []
        def runner(command, state):
            """Input: command/state dicts. Output: accepted fixture job dict."""
            calls.append(command)
            return {'status': 'queued', 'job_id': 'job-real', 'message': 'Queued, not completed'}
        command = self.command()
        result = self.submit(command, runner)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['execution_status'], 'queued')
        self.assertEqual(self.submit(command, runner), result)
        self.assertEqual(self.submit(command | {'action': 'stop'}, runner)['status'], 'refused')
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['job_id'], 'job-real')

    def test_stale_or_malformed_commands_do_not_call_actions(self):
        command = self.command()
        for changes in ({'expected_revision': 'stale'}, {'command_id': '../bad'},
                        {'action': 'submit-alpha'}, {'enable_live_api': True},
                        {'selected_option_id': 'missing'}):
            result = self.submit(command | changes, lambda *_: self.fail('must not execute'))
            self.assertEqual(result['status'], 'refused')

    def test_unknown_exception_and_process_interruption_are_not_replayed(self):
        calls = []
        def runner(*_):
            """Input: ignored args. Output: exception after a possible action effect."""
            calls.append(True)
            raise RuntimeError('lost response')
        command = self.command()
        self.assertEqual(self.submit(command, runner)['status'], 'unknown')
        self.assertEqual(self.submit(command, runner)['status'], 'unknown')
        self.assertEqual(len(calls), 1)
        command = self.command(command_id='interrupted')
        with self.assertRaises(KeyboardInterrupt):
            self.submit(command, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.assertEqual(self.submit(command, lambda *_: self.fail('no replay'))['status'], 'unknown')

    def test_stop_can_run_during_pending_start_and_stale_start_is_refused(self):
        entered, release = threading.Event(), threading.Event()
        command = self.command()
        def runner(command, state):
            """Input: command/state dicts. Output: fixture accepted result with blocked Start."""
            if command['action'] == 'start':
                entered.set()
                release.wait(5)
            else:
                self.state['runtime_control']['request_revision'] = 'stop-r2'
            return {'status': 'accepted', 'message': 'Action handler owns intent fencing'}
        thread = threading.Thread(target=lambda: self.submit(command, runner))
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.submit(self.command('stop', 'stop-1'), runner)['status'], 'accepted')
            self.assertEqual(self.submit(command | {'command_id': 'late-start'}, runner)['status'], 'refused')
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_unreadable_receipt_is_unknown_not_a_fresh_refusal(self):
        command = self.command()
        self.submit(command, lambda *_: {'status': 'accepted'})
        receipt, = self.paths.job_root.glob('application-command-*.json')
        receipt.write_text('{', encoding='utf-8')
        result = self.submit(command, lambda *_: self.fail('corrupt receipt is never replayable'))
        self.assertEqual(result['status'], 'unknown')

    def test_artifact_permission_error_is_visible_and_prevents_start(self):
        original = Path.open
        def denied(path, *args, **kwargs):
            """Input: Path/open arguments. Output: handle or injected read denial."""
            if path.name == 'run_state.json':
                raise PermissionError('fixture denial')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', denied):
            result = self.snapshot()
        self.assertTrue(result['blocker'])
        self.assertFalse(result['allowed_actions']['start'])
        self.assertTrue(result['allowed_actions']['stop'])
        self.assertEqual(result['group']['group_id'], 'legacy:' + self.run.name)
        command = {'command_id': 'stop-corrupt', 'action': 'stop', 'group_id': result['group']['group_id'],
                   'expected_revision': result['request_revision']}
        with patch.object(Path, 'open', denied):
            reply = self.submit(command, lambda *_: {'status': 'accepted'})
        self.assertEqual(reply['status'], 'accepted')

    def test_unbound_source_state_and_nonfinite_runtime_projection_are_blocked(self):
        source = self.runs / 'foreign'
        source.mkdir()
        self.state['strategy_progress'] = {'source_run_dir': str(source), 'rows': []}
        self.assertTrue(self.snapshot()['blocker'])
        self.state.pop('strategy_progress')
        self.state['strategy_progress'] = {'rows': [{'key': 'n1', 'metrics': {'sharpe': float('nan')}}]}
        result = self.snapshot()
        self.assertFalse(result['allowed_actions']['start'])
        self.assertTrue(result['allowed_actions']['stop'])
        self.assertEqual(result['group']['group_id'], 'legacy:' + self.run.name)

    def test_callback_refusal_and_ambiguous_result_remain_explicit(self):
        command = self.command()
        result = self.submit(command, lambda *_: {'status': 'refused', 'message': 'Stop won final CAS'})
        self.assertEqual(result['status'], 'refused')
        self.assertEqual(result['message'], 'Stop won final CAS')
        command = self.command(command_id='ambiguous')
        self.assertEqual(self.submit(command, lambda *_: None)['status'], 'unknown')

    def test_concurrent_duplicate_returns_unknown_without_second_dispatch(self):
        command = self.command()
        entered, release = threading.Event(), threading.Event()
        calls = []
        def runner(*_):
            """Input: ignored arguments. Output: fixture acceptance after synchronization."""
            calls.append(True)
            entered.set()
            release.wait(5)
            return {'status': 'accepted'}
        thread = threading.Thread(target=lambda: self.submit(command, runner))
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.submit(command, runner)['status'], 'unknown')
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            thread.join(5)
        self.assertEqual(self.submit(command, runner)['status'], 'accepted')

    def test_artifact_links_and_guard_links_are_refused(self):
        target = self.runs / 'outside-evidence.json'
        save(target, {'schema_version': 1, 'nodes': []})
        link = self.run / 'experiment_tree.json'
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest('Symlink creation unavailable: ' + str(exc))
        self.assertTrue(self.snapshot()['blocker'])
        link.unlink()
        command = self.command()
        self.submit(command, lambda *_: {'status': 'accepted'})
        guard, = self.paths.job_root.glob('*.guard')
        guard.unlink()
        guard.symlink_to(target)
        before = target.read_bytes()
        self.submit(command, lambda *_: self.fail('linked guard must not execute'))
        self.assertEqual(target.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
