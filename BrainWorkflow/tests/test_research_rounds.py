import importlib.util
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_orchestrator
from tests.test_workflow_stage_outcomes import checked_alpha, write_rows
from wqb.orchestrator import WorkflowOrchestrator
from wqb.workflow_stage_adapters import schedule_research_stage
from wqb.workflow_state import load_run_state, write_run_state

if importlib.util.find_spec('wqb.research_rounds'):
    from wqb import research_rounds
else:
    research_rounds = None


def write_json(path: Path, row: dict) -> None:
    """Input: Path and dict. Output: None. Write a test-only durable JSON fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row), encoding='utf-8')


def round_fixture(root: Path, stage: str = 'triage') -> tuple:
    """Input: temporary Path, stage str. Output: (controller, run Path). Build real measured schedule."""
    fixture = test_orchestrator.WorkflowOrchestratorTests()
    paths = fixture.paths(root)
    templates = paths.knowledge_root / 'wiki/30_templates/template_library.jsonl'
    first = json.loads(templates.read_text().splitlines()[0])
    second = {**first, 'template_id': 'alternate', 'skeleton': 'rank({field})',
              'hypothesis': 'Cash level captures a different economic exposure.'}
    ledger = paths.knowledge_root / 'wiki/20_semantics/data_ledger.jsonl'
    data = json.loads(ledger.read_text().splitlines()[0])
    alternate_data = {**data, 'field_id': 'alternate_cash', 'compatible_template_ids': ['alternate']}
    fixture.write_start_artifacts(root, [test_orchestrator.valid_option_row(option_id='option-1')],
                                  ledger_rows=[data, alternate_data], template_rows=[first, second])
    controller = WorkflowOrchestrator(paths)
    started = controller.start('Power Pool', 'option-1', '2026-10-11T01:00:00Z')
    run = Path(started['run_dir'])
    schedule_research_stage(paths.knowledge_root, run, 'option-1')
    schedule_path = run / 'stages/schedule/research_schedule.json'
    schedule = json.loads(schedule_path.read_text())
    schedule['template_matches'] = [match for match in schedule['template_matches']
                                    if (match['field_id'], match['template_id']) in
                                    {('cash_field', 'matrix_ts_zscore_rank'), ('alternate_cash', 'alternate')}]
    write_json(schedule_path, schedule)
    fixture.advance_to_candidate_gate(started)
    state = load_run_state(run / 'run_state.json')
    write_run_state(run / 'run_state.json', replace(state, current_stage=stage))
    write_rows(run, [checked_alpha('weak')])
    write_json(run / 'runtime_control.json', {
        'desired_state': 'running', 'enable_live_api': False, 'request_revision': 'start-approved',
        'max_simulations': 90, 'max_runtime_seconds': 3600, 'max_recoveries': 3,
    })
    write_json(run / 'runtime_status.json', {'simulation_attempts': 30})
    return controller, run


class ResearchRoundTests(unittest.TestCase):
    def test_daily_activation_reconciles_only_obsolete_budget_marker(self):
        from wqb.daily_simulation_budget import activate_daily_policy
        from wqb.runtime_control import read_runtime_control
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            control = read_runtime_control(run)
            activate_daily_policy(run, control['request_revision'], 'approved migration', '2026-10-21T01:00:00Z')
            state = load_run_state(run / 'run_state.json')
            write_run_state(run / 'run_state.json', replace(state, status='paused',
                pause_reason='research_simulation_budget_exhausted'))
            write_json(run / 'research_rounds.json', {'schema_version': 1, 'run_id': run.name,
                'status': 'blocked', 'current_round_id': 'round-0001', 'rounds': [],
                'stop_reason': 'research_simulation_budget_exhausted'})
            active = json.loads((run / 'runtime_control.json').read_text())
            write_json(run / 'runtime_control.json', {**active, 'desired_state': 'paused', 'request_revision': 'new-stop'})
            self.assertEqual(research_rounds.reconcile_research_budget_wait(run, '2026-10-22T01:00:00Z')['status'], 'unchanged')
            self.assertEqual(load_run_state(run / 'run_state.json').status, 'paused')
            write_json(run / 'runtime_control.json', active)
            before = (run / 'runtime_control.json').read_bytes()
            result = research_rounds.reconcile_research_budget_wait(run, '2026-10-22T01:00:00Z')
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(load_run_state(run / 'run_state.json').status, 'running')
            self.assertEqual((run / 'runtime_control.json').read_bytes(), before)
            self.assertEqual(research_rounds.reconcile_research_budget_wait(run, '2026-10-22T01:00:00Z')['status'], 'unchanged')

    def test_verified_legacy_budget_stop_releases_without_resume_or_quota_change(self):
        """Input: verified repair and obsolete full-batch stop. Output: assertions. Allow legal partial planning while preserving Stop."""
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            control_path = run / 'runtime_control.json'
            control = json.loads(control_path.read_text())
            write_json(control_path, {**control, 'max_simulations': 150, 'desired_state': 'paused'})
            before = control_path.read_bytes()
            write_json(run / 'runtime_status.json', {'simulation_attempts': 143})
            state = load_run_state(run / 'run_state.json')
            write_run_state(run / 'run_state.json', replace(state, status='paused',
                pause_reason='research_simulation_budget_exhausted'))
            write_json(run / 'research_rounds.json', {'schema_version': 1, 'run_id': run.name,
                'status': 'blocked', 'current_round_id': 'round-0001', 'rounds': [],
                'stop_reason': 'research_simulation_budget_exhausted'})
            with patch('wqb.recovery_cases.read_current_recovery_case', return_value={
                'case_id': 'verified', 'status': 'resolved', 'stage': 'triage'}):
                self.assertTrue(research_rounds.release_verified_partial_budget_stop(run, 'verified', 'now'))
                self.assertTrue(research_rounds.release_verified_partial_budget_stop(run, 'verified', 'restart'))
            self.assertEqual(control_path.read_bytes(), before)
            self.assertEqual(load_run_state(run / 'run_state.json').status, 'paused')
            self.assertEqual(json.loads((run / 'research_rounds.json').read_text())['status'], 'ready')

    def test_remaining_seven_simulations_create_seven_candidate_scout_cap(self):
        """Input:143 used of150. Output: assertions. Reserve only remaining quota and expose the same source cap."""
        from wqb.source_bridge import _source_batch_metadata
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            control_path = run / 'runtime_control.json'
            control = json.loads(control_path.read_text())
            write_json(control_path, {**control, 'max_simulations': 150})
            before = control_path.read_bytes()
            write_json(run / 'runtime_status.json', {'simulation_attempts': 143})
            result = research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            self.assertEqual(result['status'], 'advanced')
            ledger = json.loads((run / 'research_rounds.json').read_text())
            self.assertEqual(ledger['rounds'][-1]['budget_reserved'], 7)
            self.assertEqual(_source_batch_metadata(run)['max_alphas_per_round'], 7)
            replay = research_rounds.advance_research_round(run, 'restart', {})
            self.assertEqual(replay['round_id'], result['round_id'])
            self.assertEqual(control_path.read_bytes(), before)

    def test_corrupt_pending_selection_routes_to_maintenance_without_runner(self):
        """Input: invalid prepared alternate evidence. Output: assertions. Do not escape the driver notification path."""
        from unittest.mock import Mock
        from wqb.workflow_auto_continue import auto_continue_workflow
        from wqb.recovery_cases import classify_blocker
        with tempfile.TemporaryDirectory() as tmp:
            controller, run = round_fixture(Path(tmp))
            research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            ledger_path = run / 'research_rounds.json'
            ledger = json.loads(ledger_path.read_text())
            ledger['pending_scout_selection'] = {'selection': {'field_id': 'invented'}}
            write_json(ledger_path, ledger)
            before = ledger_path.read_bytes()
            controller.continue_once('2026-10-13T07:59:00Z')
            runner = Mock()
            result = auto_continue_workflow(controller.paths, {}, '2026-10-13T08:00:00Z',
                                            enable_live_api=True, source_batch_runner=runner)
            self.assertEqual(result['stop_reason'], 'research_planning_blocked')
            self.assertEqual(classify_blocker(result)['category'], 'code_or_contract')
            self.assertIn('selection evidence invalid', result['message'])
            self.assertEqual(ledger_path.read_bytes(), before)
            runner.assert_not_called()

    def test_alternate_cannot_use_changed_schedule_field_type(self):
        """Input: mutated local schedule semantics. Output: assertions. Only original snapshot data may authorize selection."""
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            schedule = json.loads((run / 'stages/schedule/research_schedule.json').read_text())
            manifest = json.loads((run / 'run_manifest.json').read_text())
            selected = schedule['template_matches'][0]
            for template in manifest['start_snapshot']['template_rows']:
                template['required_field_types'] = []
            for row in schedule['selected_data']:
                if row['field_id'] == selected['field_id']:
                    row['field_type'] = 'VECTOR' if row.get('field_type') != 'VECTOR' else 'MATRIX'
            self.assertEqual(research_rounds._select_next_match(
                {**schedule, 'template_matches': [selected]}, manifest, []), {})

    def test_auto_continue_zero_candidates_rotates_then_notifies_when_exhausted(self):
        """Input: real snapshot/state and zero-result runner. Output: assertions. Alternate once, then notify instead of external wait."""
        from unittest.mock import Mock
        from wqb.workflow_auto_continue import auto_continue_workflow
        from wqb.source_bridge import SourceBridgeDecision
        from wqb.research_planning import ResearchVariantsExhausted
        from wqb.recovery_cases import classify_blocker, ensure_recovery_case, advance_scripted_recovery
        with tempfile.TemporaryDirectory() as tmp:
            controller, run = round_fixture(Path(tmp))
            research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            path = run / 'stages/schedule/research_schedule.json'
            schedule = json.loads(path.read_text())
            schedule['template_matches'].reverse()
            write_json(path, schedule)
            (run / 'research_rounds.json').unlink()
            runner = Mock(side_effect=ResearchVariantsExhausted('no valid novel scheduled candidates'))
            controller.continue_once('2026-10-13T07:59:00Z')
            decision = SourceBridgeDecision('start_source_batch', 'local fixture', '', '', [], {
                'local_construction_ready': True, 'allow_live_fallback': False})
            with patch('wqb.workflow_auto_continue.WorkflowOrchestrator', return_value=controller), \
                 patch('wqb.workflow_auto_continue.inspect_scout_seed_source_bridge', return_value=decision):
                first = auto_continue_workflow(controller.paths, {}, '2026-10-13T08:00:00Z', enable_live_api=True,
                                               source_batch_runner=runner)
                second = auto_continue_workflow(controller.paths, {}, '2026-10-13T08:01:00Z', enable_live_api=True,
                                                source_batch_runner=runner)
            self.assertEqual(first['next_action'], 'workflow-auto-continue')
            self.assertEqual(second['stop_reason'], 'research_planning_blocked')
            self.assertIn('no valid novel', second['pause_reason'])
            case = ensure_recovery_case(run, classify_blocker(second), 'later')
            case = advance_scripted_recovery(run, case, {}, 'later')
            self.assertEqual(case['status'], 'awaiting_maintenance_confirmation')
            self.assertEqual(case['notification']['status'], 'pending')
            self.assertEqual(runner.call_count, 2)

    def test_zero_candidate_selection_rotates_once_without_new_round_or_budget(self):
        """Input: empty Scout and authoritative alternate. Output: assertions. Rotate locally and survive restart."""
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            # Round2 has exhausted its alternate; the previous selection is excluded.
            before = (run / 'runtime_control.json').read_bytes()
            self.assertFalse(research_rounds.rotate_exhausted_scout_plan(run, 'later', exhausted=True))
            self.assertFalse(research_rounds.rotate_exhausted_scout_plan(run, 'restart', exhausted=True))
            ledger = json.loads((run / 'research_rounds.json').read_text())
            self.assertEqual(len(ledger['rounds']), 2)
            self.assertEqual(len(ledger['exhausted_scout_selections']), 1)
            self.assertEqual((run / 'runtime_control.json').read_bytes(), before)

    def test_empty_first_scout_switches_match_and_respects_stop(self):
        """Input: first Scout with no submitted work. Output: assertions. Select a compatible alternate only once."""
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            # Recreate an unsubmitted first Scout using the preserved real snapshot.
            schedule_path = run / 'stages/schedule/research_schedule.json'
            schedule = json.loads(schedule_path.read_text())
            schedule['template_matches'].reverse()
            write_json(schedule_path, schedule)
            (run / 'research_rounds.json').unlink()
            control_path = run / 'runtime_control.json'
            before = control_path.read_bytes()
            self.assertTrue(research_rounds.rotate_exhausted_scout_plan(run, 'later', exhausted=True))
            selected = json.loads(schedule_path.read_text())['template_matches'][0]
            self.assertEqual(selected['template_id'], 'alternate')
            self.assertFalse(research_rounds.rotate_exhausted_scout_plan(run, 'restart'))
            self.assertEqual(control_path.read_bytes(), before)
            control = json.loads(before)
            write_json(control_path, {**control, 'desired_state': 'paused'})
            from wqb.runtime_control import RuntimePaused
            with self.assertRaisesRegex(RuntimePaused, 'running mission'):
                research_rounds.rotate_exhausted_scout_plan(run, 'stopped', exhausted=True)

    def test_later_round_does_not_reselect_zero_candidate_hypothesis(self):
        """Input: exhausted first hypothesis then weak alternate. Output: assertions. Do not loop back to a known empty plan."""
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            path = run / 'stages/schedule/research_schedule.json'
            schedule = json.loads(path.read_text())
            schedule['template_matches'].reverse()
            write_json(path, schedule)
            (run / 'research_rounds.json').unlink()
            self.assertTrue(research_rounds.rotate_exhausted_scout_plan(run, 'later', exhausted=True))
            state = load_run_state(run / 'run_state.json')
            write_run_state(run / 'run_state.json', replace(state, current_stage='triage'))
            write_rows(run, [checked_alpha('weak')])
            result = research_rounds.advance_research_round(run, 'next-round', {'outcome': 'no_signal'})
            self.assertEqual(result['stop_reason'], 'research_plan_unavailable')

    def setUp(self):
        """Input: None. Output: None. Require the new round contract before each behavioral test."""
        self.assertIsNotNone(research_rounds, 'durable research round controller is missing')

    def test_existing_start_authority_needs_no_extra_policy_and_original_is_not_mission(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            self.assertTrue(research_rounds.mission_round_authorized(run))
            control = json.loads((run / 'runtime_control.json').read_text())
            write_json(run / 'runtime_control.json', {**control, 'original_batch_scope_id': 'original'})
            self.assertFalse(research_rounds.mission_round_authorized(run))
            self.assertEqual(research_rounds.finish_original_batch_handoff(run, 'now')['stop_reason'],
                             'research_mission_authority_required')
            self.assertEqual(load_run_state(run / 'run_state.json').status, 'running')

    def test_partial_or_invalid_authority_is_never_completed_by_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            for row in ({}, {'max_simulations': 90}, {'invalid': True}):
                write_json(run / 'runtime_control.json', row)
                self.assertFalse(research_rounds.mission_round_authorized(run))

    def test_weak_round_archives_evidence_selects_untried_measured_match_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            before = (run / 'all_alphas.jsonl').read_bytes()
            result = research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            self.assertEqual(result['status'], 'advanced')
            self.assertEqual(result['round_id'], 'round-0002')
            self.assertFalse((run / 'all_alphas.jsonl').exists())
            self.assertEqual((run / 'rounds/round-0001/all_alphas.jsonl').read_bytes(), before)
            schedule = json.loads((run / 'stages/schedule/research_schedule.json').read_text())
            self.assertEqual(schedule['template_matches'][0]['template_id'], 'alternate')
            self.assertEqual(schedule['batch_size'], 30)
            self.assertEqual(load_run_state(run / 'run_state.json').current_stage, 'scout_seed')
            replay = research_rounds.advance_research_round(run, 'later', {'outcome': 'no_signal'})
            self.assertEqual(replay['round_id'], 'round-0002')
            self.assertEqual(len(json.loads((run / 'research_rounds.json').read_text())['rounds']), 2)

    def test_budget_and_missing_plan_are_explicit_stops_without_erasing_evidence(self):
        for kind, expected in (('budget', 'research_simulation_budget_exhausted'),
                               ('plan', 'research_plan_unavailable'),
                               ('accounting', 'research_budget_accounting_required')):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                _, run = round_fixture(Path(tmp))
                if kind == 'budget':
                    write_json(run / 'runtime_status.json', {'simulation_attempts': 90})
                elif kind == 'accounting':
                    write_json(run / 'runtime_status.json', {})
                else:
                    path = run / 'stages/schedule/research_schedule.json'
                    schedule = json.loads(path.read_text())
                    schedule['template_matches'] = schedule['template_matches'][:1]
                    write_json(path, schedule)
                before = (run / 'all_alphas.jsonl').read_bytes()
                result = research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
                self.assertEqual(result['stop_reason'], expected)
                self.assertEqual((run / 'all_alphas.jsonl').read_bytes(), before)
                self.assertFalse((run / 'rounds/round-0001').exists())

    def test_pause_pending_and_original_scope_do_not_rotate(self):
        for kind, reason in (('pause', 'user_paused'), ('pending', 'research_evidence_reconciliation_required'),
                             ('original', 'research_mission_authority_required')):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                _, run = round_fixture(Path(tmp))
                control = json.loads((run / 'runtime_control.json').read_text())
                if kind == 'pause':
                    write_json(run / 'runtime_control.json', {**control, 'desired_state': 'paused'})
                if kind == 'original':
                    write_json(run / 'runtime_control.json', {**control, 'original_batch_scope_id': 'limited'})
                if kind == 'pending':
                    write_rows(run, [checked_alpha('weak', pending=['UNKNOWN_CHECK'])])
                result = research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
                self.assertEqual(result['stop_reason'], reason)
                self.assertTrue((run / 'all_alphas.jsonl').exists())

    def test_plan_cannot_claim_seeded_data_or_invent_template(self):
        for kind in ('seeded', 'template'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                _, run = round_fixture(Path(tmp))
                path = run / 'stages/schedule/research_schedule.json'
                schedule = json.loads(path.read_text())
                if kind == 'seeded':
                    for row in schedule['selected_data']:
                        row['coverage_status'] = 'schema_seeded'
                else:
                    schedule['template_matches'][1]['skeleton'] = 'invented({field})'
                write_json(path, schedule)
                self.assertEqual(research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
                                 ['stop_reason'], 'research_plan_unavailable')

    def test_unknown_post_or_inflight_source_blocks_rotation(self):
        for event in ('SUBMISSION_STARTED', 'SUBMITTED'):
            with self.subTest(event=event), tempfile.TemporaryDirectory() as tmp:
                _, run = round_fixture(Path(tmp))
                source = run.parent / 'source'
                source.mkdir()
                write_json(run / 'stages/scout_seed/source_bridge_binding.json', {
                    'source_run_id': 'source', 'source_run_dir': str(source)})
                (source / 'simulation_events.jsonl').write_text(json.dumps({
                    'event': event, 'expression_hash': 'unknown', 'attempt_id': 'a'}) + '\n')
                self.assertEqual(research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
                                 ['stop_reason'], 'research_source_reconciliation_required')

    def test_same_field_different_verified_template_can_be_a_new_source_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            path = run / 'stages/schedule/research_schedule.json'
            schedule = json.loads(path.read_text())
            schedule['template_matches'][1]['field_id'] = schedule['template_matches'][0]['field_id']
            schedule['selected_data'][0]['compatible_template_ids'].append('alternate')
            write_json(path, schedule)
            result = research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            self.assertEqual(result['status'], 'advanced')

    def test_explicit_round_ceiling_blocks_even_when_simulations_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            control = json.loads((run / 'runtime_control.json').read_text())
            write_json(run / 'runtime_control.json', {**control, 'max_rounds': 1})
            result = research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            self.assertEqual(result['stop_reason'], 'research_round_budget_exhausted')
            self.assertTrue((run / 'all_alphas.jsonl').exists())

    def test_handoff_accepts_normal_start_without_changing_live_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            before = (run / 'runtime_control.json').read_bytes()
            result = research_rounds.finish_original_batch_handoff(run, 'now')
            self.assertEqual(result['status'], 'continue_research')
            self.assertEqual(result['next_action'], 'workflow-auto-continue')
            self.assertEqual((run / 'runtime_control.json').read_bytes(), before)

    def test_new_binding_is_not_removed_by_a_duplicate_old_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            binding = run / 'stages/scout_seed/source_bridge_binding.json'
            write_json(binding, {'source_run_id': 'new-source'})
            before = binding.read_bytes()
            replay = research_rounds.advance_research_round(run, 'later', {'outcome': 'no_signal'})
            self.assertEqual(replay['round_id'], 'round-0002')
            self.assertEqual(binding.read_bytes(), before)

    def test_prepared_transition_resumes_after_partial_archive_without_duplicate_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, run = round_fixture(Path(tmp))
            real_replace = research_rounds.os.replace

            def crash_after_move(source, target):
                """Input: source/target Paths. Output: None or OSError. Inject one crash after an actual artifact move."""
                real_replace(source, target)
                if Path(source) == run / 'all_alphas.jsonl':
                    raise OSError('simulated interruption after archive move')

            with patch('wqb.research_rounds.os.replace', side_effect=crash_after_move):
                with self.assertRaisesRegex(OSError, 'simulated interruption'):
                    controller.continue_once('2026-10-11T01:01:00Z')
            result = controller.continue_once('2026-10-11T01:02:00Z')
            self.assertEqual(result['current_stage'], 'scout_seed')
            self.assertEqual(result['status'], 'running')
            ledger = json.loads((run / 'research_rounds.json').read_text())
            self.assertEqual(len(ledger['rounds']), 2)
            self.assertNotIn('pending_transition', ledger)
            self.assertEqual(json.loads((run / 'rounds/round-0001/all_alphas.jsonl').read_text())
                             ['expression_hash'], 'parent-hash')

    def test_pause_during_interrupted_transition_keeps_prepared_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, run = round_fixture(Path(tmp))
            real_replace = research_rounds.os.replace

            def crash_after_move(source, target):
                """Input: source/target Paths. Output: None or OSError. Stop after one move to test a later Pause."""
                real_replace(source, target)
                if Path(source) == run / 'all_alphas.jsonl':
                    raise OSError('interrupted')

            with patch('wqb.research_rounds.os.replace', side_effect=crash_after_move):
                with self.assertRaises(OSError):
                    controller.continue_once('now')
            control = json.loads((run / 'runtime_control.json').read_text())
            write_json(run / 'runtime_control.json', {**control, 'desired_state': 'paused'})
            result = controller.continue_once('later')
            self.assertEqual(result['status'], 'paused')
            self.assertTrue(json.loads((run / 'research_rounds.json').read_text())['pending_transition'])
            self.assertEqual(json.loads((run / 'runtime_control.json').read_text())['desired_state'], 'paused')

    def test_corrupt_transition_cannot_move_artifacts_outside_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            write_json(run / 'research_rounds.json', {
                'schema_version': 1, 'run_id': run.name, 'current_round_id': 'round-0002', 'rounds': [],
                'pending_transition': {'parent_round_id': '../escape', 'schedule': {}, 'artifacts': []},
            })
            with self.assertRaisesRegex(ValueError, 'round transition'):
                research_rounds.advance_research_round(run, 'now', {})
            self.assertFalse((run / 'escape').exists())

    def test_delayed_callback_cannot_rotate_a_round_before_current_triage(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp), 'backtest')
            before = (run / 'all_alphas.jsonl').read_bytes()
            result = research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            self.assertEqual(result['status'], 'not_applicable')
            self.assertEqual((run / 'all_alphas.jsonl').read_bytes(), before)

    def test_unfinished_planned_source_must_finish_before_detaching_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            source = run.parent / 'source'
            source.mkdir()
            write_rows(source, [checked_alpha('weak')])
            (source / 'planned_candidates.jsonl').write_text(
                json.dumps({'expression_hash': 'parent-hash'}) + '\n' +
                json.dumps({'expression_hash': 'not-yet-submitted'}) + '\n')
            write_json(run / 'stages/scout_seed/source_bridge_binding.json', {
                'source_run_id': 'source', 'source_run_dir': str(source)})
            result = research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['stop_reason'], 'research_source_reconciliation_required')

    def test_completed_source_lineage_and_provenance_survive_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp))
            source = run.parent / 'source'
            source.mkdir()
            write_rows(source, [checked_alpha('weak')])
            write_json(run / 'stages/scout_seed/source_bridge_binding.json', {
                'source_run_id': 'source', 'source_run_dir': str(source)})
            research_rounds.advance_research_round(run, 'now', {'outcome': 'no_signal'})
            self.assertTrue((source / 'all_alphas.jsonl').exists())
            self.assertFalse((run / 'stages/scout_seed/source_bridge_binding.json').exists())
            ledger = json.loads((run / 'research_rounds.json').read_text())
            self.assertEqual(ledger['rounds'][1]['parent_source_run_id'], 'source')
            self.assertEqual(ledger['rounds'][0]['candidate_hashes'], ['parent-hash'])
            schedule = json.loads((run / 'stages/schedule/research_schedule.json').read_text())
            self.assertEqual(schedule['excluded_source_run_ids'], ['source'])
