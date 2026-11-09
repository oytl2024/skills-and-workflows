"""Read-only terminal proof against real isolated compiler/tree/workflow artifacts."""
from dataclasses import replace
from copy import deepcopy
import hashlib
import importlib
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests import test_execution_package as package_fixtures
from wqb import research_tree, tree_runtime
from wqb.benchmark_rules import (default_benchmark_rules, benchmark_rulebook_digest,
                                 benchmark_rule_to_dict)
from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
from wqb.discovery_runtime import DiscoveryRuntimeExecutor
from wqb.runtime_control import _write
from wqb.workflow_state import (create_initial_state, write_run_state, write_active_run)


NOW = '2026-11-09T00:00:00+00:00'


class ExecutionRetirementTests(unittest.TestCase):
    def test_evidence_capacity_supports_multiple_source_receipts_per_checked_row(self):
        """Input: default eight-seed/eight-iteration evidence fanout. Output: no unrelated 512-file cleanup barrier."""
        from wqb import execution_retirement as retirement
        refs = {}
        for index in range(8 * 8 * 12 + 32):
            retirement._read(self.run, 'optional-source-proof/' + str(index) + '.json', refs, optional=True)
        self.assertEqual(len(refs), 800)

    def setUp(self):
        """Input: TestCase. Output: real completed no-seed workflow in a temporary directory."""
        self.package = package_fixtures.ExecutionPackageTests()
        if os.name == 'nt' and getattr(self, 'pending_once', False):
            original_temp = tempfile.TemporaryDirectory
            def extended_temp(*args, **kwargs):
                """Input: temporary-directory args. Output: real temporary directory with native long-path spelling."""
                directory = original_temp(*args, **kwargs)
                directory.name = '\\\\?\\' + directory.name
                return directory
            with patch('tests.test_research_tree.tempfile.TemporaryDirectory', side_effect=extended_temp):
                self.package.setUp()
        else:
            self.package.setUp()
        self.addCleanup(self.package.doCleanups)
        self.fixture = self.package.fixture
        self.run, self.vault = self.fixture.run, self.fixture.vault
        rules = default_benchmark_rules()
        self.fixture.manifest['start_snapshot'].update(artifact_binding_version=2,
            benchmark_rulebook=dict(path='machine/benchmark_rules.jsonl',
                sha256=benchmark_rulebook_digest(rules),
                rules=[benchmark_rule_to_dict(row) for row in rules]))
        self.fixture.manifest['start_snapshot']['research_policy']['deterministic_repair'] = True
        self.package.enable()
        if getattr(self, 'simulate_repair', False):
            from tests.test_repair_search import search_fixture
            from wqb.initial_research_planning import _annotation_context, DATA_CHARACTERISTICS_PATH
            _, policy = search_fixture()
            path, source = next(iter(self.fixture.compiler_resources['source_index'].items()))
            ref = dict(source_path=path, sha256=source['content_hash'],
                       capture_date=source['captured_at'][:10], kind='documented')
            policy['rules'] = [dict(policy['rules'][0], grid=[8], evidence_refs=[ref])]
            for trait in policy['traits'].values():
                trait['evidence_refs'] = [ref]
            self.fixture.manifest['start_snapshot']['repair_search_policy'] = policy
            artifact = self.read(DATA_CHARACTERISTICS_PATH)
            artifact['repair_search_policy_sha256'] = _annotation_context(
                self.fixture.compiler_resources, self.fixture.manifest)['repair_search_policy_sha256']
            _write(self.run / DATA_CHARACTERISTICS_PATH, artifact)
            _write(self.run / 'run_manifest.json', self.fixture.manifest)
        self.fixture.tree['nodes'] = self.fixture.tree['nodes'][:1]
        self.fixture.tree['nodes'][0]['targets'] = dict(baseline=[], treatment=[])
        self.fixture.freeze()
        self.source = self.run.parent / 'exact-source'

        def execute(config, metadata):
            """Input: existing tree config/metadata dicts. Output: local measured source, no requests."""
            self.source.mkdir()
            sharpe, fitness = getattr(self, 'seed_metrics', (.1, .1))
            rows = [self.fixture.checked(arm=arm, sharpe=sharpe, fitness=fitness,
                failed=['LOW_SHARPE'], pending=[]) for arm in ('baseline', 'treatment')]
            (self.source / 'run_meta.jsonl').write_text(json.dumps(dict(
                ai_plan_receipt=config['ai_plan_receipt'], research_round_id=config['research_round_id']))+'\n')
            self.rows = rows
            for name, values in [('all_alphas.jsonl', rows), ('planned_candidates.jsonl', rows),
                    ('simulation_events.jsonl', [dict(row, event='CHECKED') for row in rows])]:
                (self.source / name).write_text(''.join(json.dumps(row)+'\n' for row in values))
            return dict(run_dir=str(self.source))

        config = dict(self.fixture.scope, knowledge_root=str(self.vault), active_workflow_run_dir=str(self.run))
        tree_runtime.continue_tree(self.run, config, NOW, enable_live_api=True, source_batch_runner=execute)
        result = tree_runtime.continue_tree(self.run, config, NOW)
        self.assertTrue(result.get('tree_complete'), result)
        # The compiler fixture has minimal index rows; add the canonical writer's
        # descriptive fields before exercising the real recording transaction.
        index = self.vault / 'machine/source_index.jsonl'
        index.write_text(''.join(json.dumps(dict(row, contents='Offline compiler source',
            update_check='fixture'))+'\n' for row in self.fixture.compiler_resources['source_index'].values()))
        state = create_initial_state(self.run.name, self.run, 'Offline completion proof', NOW)
        stages = dict(state.stages)
        for name in ('objective_selected', 'schedule'):
            stages[name] = replace(stages[name], status='completed', completed_at=NOW,
                                  evidence_paths=[str(self.run / 'run_manifest.json')])
        write_run_state(self.run / 'run_state.json', replace(state, stages=stages,
            status='running', current_stage='scout_seed', last_completed_stage='schedule'))
        write_active_run(self.run.parent, self.run.name, self.run)
        paths = OrchestratorPaths(project_root=self.fixture.root, workflow_root=self.fixture.root,
                                  knowledge_root=self.vault, run_root=self.run.parent)
        from wqb.repair_runtime import RepairRuntimeExecutor
        if getattr(self, 'simulate_repair', False):
            self.client = Mock()
            self.client.knowledge_root = self.vault
            self.client.measurement_window_required = False
            self.client.get_json.side_effect = self.platform_response
            self.enterContext(patch('wqb.cli._live_gate_kwargs', return_value={}))
            self.enterContext(patch('wqb.cli.require_readiness_gate'))
            self.enterContext(patch('wqb.cli.build_client', return_value=self.client))
            self.transport_submit = self.enterContext(patch('wqb.cli.submit_simulation', side_effect=self.submitted))
            self.enterContext(patch('wqb.cli.poll_simulation', return_value=dict(alpha='child')))
            if getattr(self, 'pending_once', False):
                self.enterContext(patch('wqb.repair_runtime.REPAIR_PROGRESS_RETRY_SECONDS', 0))
        controller = WorkflowOrchestrator(paths, discovery_executor=DiscoveryRuntimeExecutor(config),
            repair_executor=RepairRuntimeExecutor(config, enable_live_api=getattr(self, 'simulate_repair', False)))
        for _ in range(16):
            completed = controller.continue_once(NOW)
            if completed.get('status') == 'paused' and completed.get('current_stage') == 'repair':
                completed = controller.resume(NOW)
                continue
            if completed.get('current_stage') == 'candidate_gate':
                completed = controller.request_candidate_approval_from_checked_results(NOW)
                self.waiting_state = deepcopy(completed)
                if getattr(self, 'leave_waiting', False):
                    break
                controller.approve_candidates(['child:' + self.child_hash()], NOW, 'isolated explicit fixture approval')
                continue
            if completed.get('status') != 'running':
                break
        self.assertEqual(completed.get('status'),
                         'waiting_for_user' if getattr(self, 'leave_waiting', False) else 'completed', completed)
        if not hasattr(self, 'seed_metrics'):
            self.assertEqual(self.read('stages/scout_seed/seed_selection.json')['selected'], [])

    def submitted(self, client, payload):
        """Input: fake client/submission dict. Output: fake progress URL; capture real runtime payload only."""
        self.submitted_payload = deepcopy(payload)
        return 'offline/progress/child'

    def child_hash(self):
        """Input: fixture. Output: CLI identity str of the actual submitted child."""
        from wqb.cli import simulation_identity_hash
        return simulation_identity_hash(self.submitted_payload['regular'], self.submitted_payload['settings'])

    def platform_response(self, endpoint):
        """Input: mocked GET endpoint str. Output: synthetic raw platform detail/full checks for the actual child."""
        qualified = getattr(self, 'qualified_child', False)
        baseline = [dict(name='LOW_SHARPE', result='PASS'),
                    dict(name='LOW_FITNESS', result='PASS' if qualified else 'FAIL')]
        if endpoint == '/alphas/child' and getattr(self, 'pending_once', False) and not getattr(self, 'pending_seen', False):
            self.pending_seen = True
            baseline[1]['result'] = 'PENDING'
        if getattr(self, 'deferred_checks', False):
            baseline.extend(dict(name=name, result='PENDING') for name in ('SELF_CORRELATION', 'PROD_CORRELATION'))
        metrics = dict(sharpe=1.8, fitness=1.2 if qualified else .9, returns=.12, turnover=.15,
                       startDate='2020-01-01', endDate='2025-12-31', checks=baseline)
        if endpoint == '/alphas/child':
            return dict(id='child', status='UNSUBMITTED', regular=dict(code=self.submitted_payload['regular']),
                        settings=deepcopy(self.submitted_payload['settings']), **{'is': metrics})
        if endpoint == '/alphas/child/check':
            return {'is': dict(checks=[dict(name=name, result='PASS') for name in
                                      ('SELF_CORRELATION', 'PROD_CORRELATION')])}
        raise AssertionError('Unexpected fake transport endpoint: ' + endpoint)

    def repair_fixture(self, qualified=False, waiting=False, pending=False, deferred=False):
        """Input: candidate/wait bools. Output: real scheduler/runtime child fixture with mock transport only."""
        other = ExecutionRetirementTests()
        other.seed_metrics = (1.6, .8)
        other.simulate_repair = True
        other.qualified_child = qualified
        other.leave_waiting = waiting
        other.pending_once = pending
        other.deferred_checks = deferred
        self.addCleanup(other.doCleanups)
        other.setUp()
        self.assertEqual(other.transport_submit.call_count, 1)
        return other

    def read(self, relative):
        """Input: run-relative str. Output: JSON object from isolated fixture."""
        return json.loads((self.run / relative).read_bytes())

    def proof(self):
        """Input: none. Output: production read-only proof dict for isolated run."""
        return importlib.import_module('wqb.execution_retirement').terminal_retirement_proof(self.run)

    def snapshot(self):
        """Input: none. Output: exact temporary-tree paths/bytes/mtimes, including guard files."""
        return {str(path.relative_to(self.fixture.root)):
                (path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns)
                for path in self.fixture.root.rglob('*')}

    def test_completed_no_seed_proof_is_pure_and_identity_bound(self):
        before = self.snapshot()
        result = self.proof()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['run_id'], self.run.name)
        self.assertEqual(result['seal']['sha256'], hashlib.sha256(
            (self.run / 'runtime/execution_package/seal.json').read_bytes()).hexdigest())
        self.assertEqual(set(result['record_evidence']), {'local', 'raw', 'machine'})
        self.assertEqual(result['summary']['seed']['selected'], [])
        self.assertEqual(result['summary']['repair']['execution'], 'skipped_no_eligible_seeds')
        self.assertEqual(len(result['summary']['checked_rows']), 2)
        self.assertFalse(result['summary']['authority_changed'])
        self.assertEqual(self.proof(), result)

    def test_completion_flags_cannot_hide_protected_stages_or_unsynced_record(self):
        original = self.read('run_state.json')
        for changes in (dict(current_stage='scout_seed'), dict(current_stage='user_approval'),
                        dict(status='completed_with_warnings'), dict(research_record_synced=False),
                        dict(waiting_for_user=True)):
            with self.subTest(changes=changes):
                _write(self.run / 'run_state.json', dict(original, **changes))
                with self.assertRaisesRegex(ValueError, 'terminal_state'):
                    self.proof()
        _write(self.run / 'run_state.json', original)

    def test_stop_damaged_control_and_waits_reject_without_writes(self):
        original = self.read('runtime_control.json')
        for control in (dict(original, desired_state='paused'), {}, dict(original, invalid=True)):
            _write(self.run / 'runtime_control.json', control)
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError, 'runtime_control'):
                self.proof()
            self.assertEqual(self.snapshot(), before)
        _write(self.run / 'runtime_control.json', original)
        for relative, value in [('runtime/daily_budget_wait.json', dict(status='waiting')),
                                ('runtime/tree_budget_wait.json', dict(required_pair_count=2)),
                                ('stages/repair/repair_execution.json', dict(run_id=self.run.name,
                                    status='completed', attempts=[dict(phase='result_unknown')]))]:
            with self.subTest(relative=relative):
                _write(self.run / relative, value)
                with self.assertRaises(ValueError):
                    self.proof()
                (self.run / relative).unlink()

    def test_record_destinations_require_actual_matching_content(self):
        raw = self.vault / 'raw/research/runs' / self.run.name / 'research_record.md'
        ledger = self.vault / 'machine/research_records.jsonl'
        for path in (raw, ledger):
            original = path.read_bytes()
            with self.subTest(path=path.name):
                path.write_bytes(b'{}\n')
                with self.assertRaisesRegex(ValueError, 'record'):
                    self.proof()
                path.write_bytes(original)

    def test_pending_unknown_and_corrupt_exact_source_evidence_reject(self):
        path = self.source / 'simulation_events.jsonl'
        original = path.read_bytes()
        for row in (dict(event='SUBMISSION_STARTED', attempt_id='unknown', expression_hash='unresolved'),
                    dict(event='SUBMITTED', expression_hash='pending', progress_url='pending-url'),
                    dict(event='CHECK_PENDING', expression_hash='pending')):
            with self.subTest(event=row['event']):
                path.write_bytes(original + (json.dumps(row)+'\n').encode())
                with self.assertRaisesRegex(ValueError, 'source'):
                    self.proof()
        path.write_bytes(b'{broken')
        with self.assertRaisesRegex(ValueError, 'source'):
            self.proof()

    def test_tampered_projection_decision_and_seal_reject(self):
        paths = [self.run / 'runtime/tree_execution.json',
                 self.run / 'runtime/execution_package/seal.json']
        paths += list((self.run / 'runtime/research_plans').glob('tree-decision-*.json'))[-1:]
        for path in paths:
            original = path.read_bytes()
            value = json.loads(original)
            value['tree_digest'] = 'bad'
            path.write_text(json.dumps(value))
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                self.proof()
            path.write_bytes(original)

    def test_verified_closed_recovery_is_retained_and_damaged_proof_blocks(self):
        from wqb.recovery_cases import ensure_recovery_case, classify_blocker
        from wqb.maintenance_resolution import approve_repair, verify_and_resolve
        from wqb.runtime_control import update_runtime_status
        case = ensure_recovery_case(self.run, classify_blocker(dict(next_action='no_progress_detected')), NOW)
        update_runtime_status(self.run, recovery_case=case)
        approved = approve_repair(self.run, case['case_id'], 'isolated fixture approval')
        with patch('wqb.maintenance_resolution.subprocess.run', return_value=
                   subprocess.CompletedProcess([], 0, '', 'Ran 12 tests in 1s\nOK\n')):
            verify_and_resolve(self.run, case['case_id'], approved['repair_approval']['approval_id'])
        update_runtime_status(self.run, status='completed', reason='', next_wake_at='')
        before = self.snapshot()
        self.assertTrue(self.proof()['eligible'])
        self.assertEqual(self.snapshot(), before)
        path = self.run / 'runtime/maintenance_verification' / (case['case_id']+'.json')
        value = json.loads(path.read_bytes())
        _write(path, dict(value, tests_run=0))
        with self.assertRaisesRegex(ValueError, 'recovery'):
            self.proof()

    def test_historical_expired_cooldown_is_not_a_current_blocker(self):
        path = self.source / 'rate_limit_state.json'
        value = dict(status='cooldown', retry_at='2020-01-01T00:00:00+00:00',
                     updated_at='2020-01-01T00:00:00+00:00', attempt_count=1, consecutive_429_count=1)
        _write(path, value)
        self.assertTrue(self.proof()['eligible'])
        for changes in (dict(retry_at='2099-01-01T00:00:00+00:00'),
                        dict(consecutive_429_count=3), dict(retry_at='broken')):
            with self.subTest(changes=changes):
                _write(path, dict(value, **changes))
                with self.assertRaisesRegex(ValueError, 'source'):
                    self.proof()

    def test_missing_seal_and_unknown_record_schema_fail_closed(self):
        path = self.run / 'runtime/execution_package/seal.json'
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            self.proof()
        path.write_bytes(original)
        record = self.read('research_record.json')
        _write(self.run / 'research_record.json', dict(record, extra_authority=True))
        with self.assertRaisesRegex(ValueError, 'record'):
            self.proof()

    def test_new_pending_artifact_and_unresolved_recovery_cannot_hide_behind_completion(self):
        for root, relative, value in (
                (self.source, 'pending_checks/identity.json', dict(status='pending')),
                (self.source, 'result_unknown.json', dict(status='result_unknown')),
                (self.run, 'runtime/recovery/' + 'a'*24 + '.json', dict(case_id='a'*24, status='waiting_external'))):
            with self.subTest(relative=relative):
                _write(root / relative, value)
                with self.assertRaises(ValueError):
                    self.proof()
                (root / relative).unlink()

    def test_actual_selected_seed_finite_stop_has_bound_repair_summary(self):
        other = ExecutionRetirementTests()
        other.seed_metrics = (1.6, .8)
        other.setUp()
        self.addCleanup(other.doCleanups)
        selection = other.read('stages/scout_seed/seed_selection.json')
        self.assertTrue(selection['selected'])
        before = other.snapshot()
        proof = other.proof()
        self.assertEqual(other.snapshot(), before)
        self.assertEqual(proof['summary']['repair']['status'], 'completed')
        self.assertTrue(proof['summary']['repair']['attempts'])
        repair = other.read('stages/repair/repair_execution.json')
        repair['attempts'][0]['plan']['evidence_digest'] = '0'*64
        _write(other.run / 'stages/repair/repair_execution.json', repair)
        with self.assertRaisesRegex(ValueError, 'repair'):
            other.proof()

    def test_unaccounted_derived_artifacts_refuse_a_boolean_completion_shortcut(self):
        for relative, value in (
                ('stages/batch_generation/discovery_execution.json', dict(status='paused', recovery_eligible=True)),
                ('research_rounds.json', dict(pending_transition=dict(next_stage='scout_seed'))),
                ('stages/repair/parents/orphan/result_unknown.json', dict(status='result_unknown'))):
            with self.subTest(relative=relative):
                _write(self.run / relative, value)
                with self.assertRaises(ValueError):
                    self.proof()
                (self.run / relative).unlink()

    def test_false_terminal_flags_do_not_override_stage_or_check_evidence(self):
        state = self.read('run_state.json')
        for name in ('repair', 'user_approval', 'research_record_sync'):
            altered = json.loads(json.dumps(state))
            altered['stages'][name]['status'] = 'paused'
            _write(self.run / 'run_state.json', altered)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'terminal_state'):
                self.proof()
        _write(self.run / 'run_state.json', state)
        altered = json.loads(json.dumps(state))
        altered['stages']['research_record_sync']['status'] = 'skipped'
        _write(self.run / 'run_state.json', altered)
        with self.assertRaisesRegex(ValueError, 'terminal_state'):
            self.proof()
        _write(self.run / 'run_state.json', state)
        _write(self.run / 'stages/backtest/check_recovery.json',
               dict(run_id=self.run.name, status='paused', recovery_eligible=True))
        with self.assertRaisesRegex(ValueError, 'source'):
            self.proof()

    def test_package_change_between_authentication_and_ref_capture_rejects(self):
        from wqb.execution_package import load_execution_package
        def changed(run):
            """Input: fixture run Path. Output: genuine loaded package followed by a concurrent seal mutation."""
            result = load_execution_package(run)
            _write(run / 'runtime/execution_package/seal.json', dict(result['seal'], run_id='other'))
            return result
        with patch('wqb.execution_retirement.load_execution_package', side_effect=changed):
            with self.assertRaises(ValueError):
                self.proof()

    def test_actual_runtime_child_and_scheduler_completion_are_read_only_provable(self):
        other = self.repair_fixture()
        before = other.snapshot()
        proof = other.proof()
        self.assertEqual(before, other.snapshot())
        children = [row for row in proof['summary']['checked_rows'] if row['alpha_id'] == 'child']
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]['expression_hash'], other.child_hash())
        self.assertTrue(proof['summary']['repair']['attempts'][0]['children'])

    def test_hardpass_raw_cache_is_preserved_after_expiry_without_renewal(self):
        from wqb.candidate_evidence import _canonical
        other = self.repair_fixture(qualified=True)
        path = other.vault / 'machine/candidate_evidence' / (hashlib.sha256(b'child').hexdigest()+'.json')
        value = json.loads(path.read_bytes())
        value.update(checked_at=1000, expires_at=2000)
        value.pop('integrity_sha256')
        value['integrity_sha256'] = hashlib.sha256(_canonical(value).encode()).hexdigest()
        _write(path, value)
        before = other.snapshot()
        proof = other.proof()
        self.assertEqual(before, other.snapshot())
        self.assertEqual(proof['summary']['candidate_evidence'][0]['record'], value)
        self.assertFalse(proof['summary']['grants_final_submission_authority'])
        self.assertIn(str(path), [ref['path'] for ref in proof['evidence_refs']])

    def test_actual_qualified_child_still_waiting_for_approval_refuses(self):
        other = self.repair_fixture(qualified=True, waiting=True)
        with self.assertRaisesRegex(ValueError, 'terminal_state'):
            other.proof()

    def test_actual_pending_check_recovery_closes_one_post_and_retains_receipts(self):
        other = self.repair_fixture(pending=True)
        receipts = list((other.run / 'stages/repair/parents').glob('*/iterations/*/pending_checks/*.json'))
        self.assertEqual(len(receipts), 1)
        before = other.snapshot()
        proof = other.proof()
        self.assertEqual(before, other.snapshot())
        self.assertIn(str(receipts[0]), [ref['path'] for ref in proof['evidence_refs']])
        receipt = json.loads(receipts[0].read_bytes())
        _write(receipts[0], dict(receipt, expression_hash='other'))
        with self.assertRaises(ValueError):
            other.proof()

    def test_actual_child_source_and_consumed_receipt_cannot_be_forged(self):
        other = self.repair_fixture()
        repair = other.read('stages/repair/repair_execution.json')
        plan = repair['attempts'][0]['plan']
        source = next((other.run / 'stages/repair/parents').glob('*/iterations/*'))
        paths = [source / 'repair_plan.json', source / 'all_alphas.jsonl',
                 source / 'simulation_events.jsonl', other.run / ('runtime/repair_decisions/deterministic-'+plan['evidence_digest']+'.json')]
        for path in paths:
            original = path.read_bytes()
            if path.suffix == '.jsonl':
                rows = [json.loads(line) for line in original.decode().splitlines()]
                rows[-1]['alpha_id'] = 'other'
                path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            else:
                value = json.loads(original)
                value['status' if 'status' in value else 'parent_alpha_id'] = 'validated' if 'status' in value else 'other'
                _write(path, value)
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                other.proof()
            path.write_bytes(original)

    def test_candidate_raw_cache_and_queue_binding_required_but_invalidation_not_renewed(self):
        from wqb.candidate_evidence import invalidate_candidate_evidence, invalidate_self_pool, _canonical
        other = self.repair_fixture(qualified=True)
        path = other.vault / 'machine/candidate_evidence' / (hashlib.sha256(b'child').hexdigest()+'.json')
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            other.proof()
        path.write_bytes(original)
        value = json.loads(original)
        value['alpha_detail']['regular']['code'] = 'invented'
        value.pop('integrity_sha256')
        value['integrity_sha256'] = hashlib.sha256(_canonical(value).encode()).hexdigest()
        _write(path, value)
        with self.assertRaises(ValueError):
            other.proof()
        path.write_bytes(original)
        invalidate_candidate_evidence(other.client, 'child', 'historical checks no longer reusable')
        invalidate_self_pool(other.vault, 'separate account change')
        before = other.snapshot()
        proof = other.proof()
        self.assertEqual(before, other.snapshot())
        self.assertTrue(proof['summary']['candidate_evidence'][0]['record']['invalidated'])
        self.assertFalse(proof['summary']['candidate_evidence'][0]['eligibility_revalidated'])
        queue = other.run / 'approved_candidates.jsonl'
        rows = [json.loads(line) for line in queue.read_text().splitlines()]
        rows[0]['source_run_id'] = 'other'
        queue.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        with self.assertRaises(ValueError):
            other.proof()

    def test_completed_research_defers_only_nonrequired_submission_checks(self):
        other = self.repair_fixture(deferred=True)
        proof = other.proof()
        child = next(row for row in proof['summary']['checked_rows'] if row['alpha_id'] == 'child')
        self.assertEqual(set(child['pending']), {'SELF_CORRELATION', 'PROD_CORRELATION'})
        self.assertFalse(child['hard_pass'])


if __name__ == '__main__':
    unittest.main()
