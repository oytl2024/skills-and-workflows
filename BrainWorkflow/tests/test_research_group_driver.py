"""Offline lifecycle tests with real frozen contexts, accounting and fake processes."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_exploration_eligibility as source_fixture
from wqb.benchmark_rules import (START_SNAPSHOT_VERSION, default_benchmark_rules, benchmark_rule_to_dict,
    benchmark_rulebook_digest, benchmark_rules_path_for_knowledge, write_benchmark_rules_jsonl)
from wqb.exploration_eligibility import certify_exploration_resources, validate_exploration, build_exploration_snapshot
from wqb.group_preparation import complete_group_lanes, prepare_group_lanes, _digest
from wqb.research_group import create_group, read_group, stop_group
from wqb.runtime_control import _write, read_runtime_control, request_runtime_state, update_runtime_status
from wqb.daily_simulation_budget import charge_daily_budget, read_daily_budget
from wqb.orchestrator import WorkflowOrchestrator


def valid_option(**overrides):
    """Input: option overrides dict. Output: strict fictional offline option dict."""
    return dict(title='Offline', primary_incentive='power_pool', secondary_incentives=[],
        why_now='Measured fixture', candidate_scope='USA D1 TOP3000', expected_asset_value='Offline',
        correlation_risk='low', resource_cost='small', failure_modes=[], decision_needed='Start',
        evidence=[dict(source_type='ledger', path='machine/data_ledger.jsonl', title='Fixture', timestamp='2026-07-16')],
        score=dict(total=1.0, components={}, penalties={}, reasons=['measured fixture']), **overrides)


class ResearchGroupDriverTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: None; isolate raw sources and all generated state."""
        self.fixture = source_fixture.ExplorationCertificationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.paths = SimpleNamespace(project_root=self.fixture.root,
            workflow_root=Path(__file__).resolve().parents[1],
            knowledge_root=self.fixture.vault, run_root=self.fixture.root / 'runs')
        self.spawned = []

    def prepared(self, count=1, live=True):
        """Input: count int/live bool. Output: group dict; compile actual certified fixtures."""
        resources = []
        for index in range(count):
            resource = deepcopy(self.fixture.resources)
            resource['settings']['decay'] = index + 4
            resources.append(resource)
        group = create_group(self.paths.run_root,
            [dict(run_id='lane-' + str(i), plan_digest=_digest(row)) for i, row in enumerate(resources)],
            dict(enable_live_api=live, max_runtime_seconds=3600, max_recoveries=3))
        rules = default_benchmark_rules()
        compiled = []
        for lane, resource in zip(group['lanes'], resources):
            run = self.paths.run_root / lane['run_id']
            snapshot = dict(artifact_binding_version=START_SNAPSHOT_VERSION, selected_option=valid_option(option_id='offline'),
                selected_scope=self.fixture.scope,
                research_policy=dict(paired_scout=True, exploration_scout=True, exploration_policy_version=1),
                benchmark_rulebook=dict(path='machine/benchmark_rules.jsonl',
                    sha256=benchmark_rulebook_digest(rules), rules=[benchmark_rule_to_dict(r) for r in rules]))
            _write(run / 'run_manifest.json', dict(run_id=run.name, knowledge_root=str(self.paths.knowledge_root),
                selected_scope=self.fixture.scope, selected_option_id='offline', objective='Offline',
                created_at='2026-10-23T00:00:00+00:00', start_snapshot=snapshot))
            cert = certify_exploration_resources(run, self.paths.knowledge_root, resource, self.fixture.scope)
            receipt = validate_exploration(self.fixture.design, resource, self.fixture.scope)
            compiled.append(build_exploration_snapshot([receipt], resource_certificates=[cert]))
        return complete_group_lanes(self.paths, Path(group['group_dir']), compiled)

    def spawn(self, argv, **kwargs):
        """Input: argv list/Popen kwargs. Output: fake process; never launch any workflow."""
        self.spawned.append((argv, kwargs))
        return SimpleNamespace(pid=800000 + len(self.spawned))

    def test_producer_snapshot_completes_through_real_schedule_gate(self):
        write_benchmark_rules_jsonl(benchmark_rules_path_for_knowledge(self.paths.knowledge_root), default_benchmark_rules())
        prepared = prepare_group_lanes(self.paths, [self.fixture.resources], self.fixture.scope,
            valid_option(option_id='offline'),
            dict(enable_live_api=False, max_runtime_seconds=3600, max_recoveries=3))
        group = prepared['group']
        receipt = validate_exploration(self.fixture.design, self.fixture.resources, self.fixture.scope)
        snapshot = build_exploration_snapshot([receipt], resource_certificates=prepared['certificates'])
        complete_group_lanes(self.paths, Path(group['group_dir']), [snapshot])
        run = self.paths.run_root / group['lanes'][0]['run_id']
        manifest = json.loads((run / 'run_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['start_snapshot']['artifact_binding_version'], START_SNAPSHOT_VERSION)
        self.assertTrue((run / 'run_state.json').is_file())
        from wqb.research_group_driver import initialize_group_runtime
        initialize_group_runtime(self.paths, group)

    def test_initialize_n_lanes_paused_idempotent_and_shared_daily(self):
        from wqb.research_group_driver import initialize_group_runtime
        for count in (1, 2, 4):
            with self.subTest(count=count):
                # Each subcase has independent real roots and accounting.
                if count != 1:
                    self.setUp()
                group = self.prepared(count)
                result = initialize_group_runtime(self.paths, group)
                self.assertEqual(result['desired_state'], 'paused')
                revisions = []
                for lane in group['lanes']:
                    run = self.paths.run_root / lane['run_id']
                    control = read_runtime_control(run)
                    self.assertEqual(control['desired_state'], 'paused')
                    self.assertTrue(control['enable_live_api'])
                    self.assertEqual(control['max_runtime_seconds'], 3600)
                    self.assertEqual(control['max_recoveries'], 3)
                    self.assertEqual(control['simulation_attempts'], 0)
                    self.assertEqual(control['simulation_budget_mode'], 'daily')
                    revisions.append(control['request_revision'])
                initialize_group_runtime(self.paths, group)
                self.assertEqual(revisions, [read_runtime_control(self.paths.run_root / l['run_id'])['request_revision']
                                            for l in group['lanes']])
                self.assertFalse((self.paths.run_root / 'active_run.json').exists())
                self.assertEqual(json.loads((self.paths.run_root / 'active_research_group.json').read_text()),
                                 {'group_id': group['group_id']})

    def test_missing_prepared_state_has_no_partial_authority_or_pointer(self):
        from wqb.research_group_driver import initialize_group_runtime
        group = self.prepared(2)
        (self.paths.run_root / 'lane-1/run_state.json').unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            initialize_group_runtime(self.paths, group)
        self.assertFalse((self.paths.run_root / 'lane-0/runtime_control.json').exists())
        self.assertFalse((self.paths.run_root / 'active_research_group.json').exists())

    def test_initialize_preserves_stop_and_cumulative_usage(self):
        from wqb.research_group_driver import initialize_group_runtime
        group = self.prepared()
        initialize_group_runtime(self.paths, group)
        run = self.paths.run_root / 'lane-0'
        charge_daily_budget(run, 7, 'offline-charge')
        update_runtime_status(run, elapsed_seconds=67, recoveries_used=2)
        paused = request_runtime_state(run, 'paused')
        initialize_group_runtime(self.paths, group)
        control = read_runtime_control(run)
        self.assertEqual(control['request_revision'], paused['request_revision'])
        self.assertEqual(control['simulation_attempts'], 7)
        self.assertEqual(control['elapsed_seconds'], 67)
        self.assertEqual(control['recoveries_used'], 2)

    def test_double_start_and_lost_ack_do_not_duplicate_workers(self):
        from wqb.research_group_driver import initialize_group_runtime, start_group_workers
        group = self.prepared(2)
        initialize_group_runtime(self.paths, group)
        revision = group['request_revision']
        first = start_group_workers(self.paths, group, expected_revision=revision, config={}, spawn_runner=self.spawn)
        self.assertEqual(len(self.spawned), 2)
        replay = start_group_workers(self.paths, group, expected_revision=revision, config={}, spawn_runner=self.spawn)
        self.assertEqual(first['request_revision'], replay['request_revision'])
        self.assertEqual(len(self.spawned), 2)
        self.assertEqual(first['workers'], replay['workers'])
        self.assertEqual(read_group(Path(group['group_dir']))['desired_state'], 'running')
        self.assertTrue(all('-m' in args and 'wqb.research_group_driver' in args for args, _ in self.spawned))

    def test_crash_after_resume_before_receipt_can_recover_same_start(self):
        from unittest.mock import patch
        from wqb import research_group_driver as driver
        group = self.prepared(2)
        driver.initialize_group_runtime(self.paths, group)
        write = driver._write
        def crash(path, payload):
            """Input: fixture path/payload. Output: write except exact post-Resume receipt crash."""
            if Path(path).name == 'worker_start.json' and payload.get('status') == 'running':
                raise OSError('fixture crash after Resume')
            return write(path, payload)
        with patch.object(driver, '_write', side_effect=crash), self.assertRaises(OSError):
            driver.start_group_workers(self.paths, group, expected_revision=group['request_revision'],
                                       config={}, spawn_runner=self.spawn)
        current = read_group(Path(group['group_dir']))
        self.assertEqual(current['desired_state'], 'running')
        self.assertFalse(self.spawned)
        result = driver.start_group_workers(self.paths, group, expected_revision=group['request_revision'],
                                            config={}, spawn_runner=self.spawn)
        self.assertEqual(result['request_revision'], current['request_revision'])
        self.assertEqual(len(self.spawned), 2)

    def test_spawn_exception_is_durable_unknown_not_replayed(self):
        from wqb.research_group_driver import initialize_group_runtime, start_group_workers
        group = self.prepared()
        initialize_group_runtime(self.paths, group)
        def lost_ack(argv, **kwargs):
            """Input: spawn arguments. Output: exception after an uncertain launch."""
            self.spawned.append(argv)
            raise OSError('private credential must not be recorded')
        first = start_group_workers(self.paths, group, expected_revision=group['request_revision'], config={}, spawn_runner=lost_ack)
        second = start_group_workers(self.paths, group, expected_revision=group['request_revision'], config={}, spawn_runner=self.spawn)
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(first['workers'][0]['status'], 'unknown')
        self.assertEqual(second['workers'][0]['status'], 'unknown')
        self.assertNotIn('private credential', json.dumps(first))

    def test_concurrent_double_start_launches_each_lane_once(self):
        from wqb.research_group_driver import start_group_workers
        group = self.prepared(2)
        barrier = Barrier(2)

        def start():
            """Input: none. Output: group dict after synchronized offline Start."""
            barrier.wait(timeout=10)
            return start_group_workers(self.paths, group, expected_revision=group['request_revision'],
                config={}, spawn_runner=self.spawn)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(start) for _ in range(2)]
            results = [future.result(timeout=30) for future in futures]
        self.assertEqual(len(self.spawned), 2)
        self.assertEqual(results[0]['request_revision'], results[1]['request_revision'])
        self.assertEqual(results[0]['workers'], results[1]['workers'])

    def test_stop_between_start_validation_and_resume_wins_cas(self):
        from wqb.research_group import resume_group
        from wqb.research_group_driver import start_group_workers
        group = self.prepared()

        def concurrent_stop(path, revision, **kwargs):
            """Input: group Path/revision str. Output: failed resume after newer durable Stop."""
            stop_group(path, revision)
            return resume_group(path, revision, **kwargs)

        with patch('wqb.research_group_driver.resume_group', side_effect=concurrent_stop):
            with self.assertRaisesRegex(ValueError, 'stale group intent'):
                start_group_workers(self.paths, group, expected_revision=group['request_revision'],
                    config={}, spawn_runner=self.spawn)
        self.assertEqual(read_group(Path(group['group_dir']))['desired_state'], 'paused')
        self.assertEqual(self.spawned, [])
        self.assertEqual(read_runtime_control(self.paths.run_root / 'lane-0')['desired_state'], 'paused')

    def test_resume_retains_original_shared_usage_and_authority(self):
        from wqb.research_group_driver import start_group_workers
        group = self.prepared(2)
        started = start_group_workers(self.paths, group, expected_revision=group['request_revision'],
            config={}, spawn_runner=self.spawn)
        run = self.paths.run_root / 'lane-0'
        charge_daily_budget(run, 7, 'before-stop')
        update_runtime_status(run, elapsed_seconds=123, recoveries_used=2)
        stopped = stop_group(Path(group['group_dir']), started['request_revision'])
        with patch('wqb.research_group_driver._alive', return_value=True):
            resumed = start_group_workers(self.paths, group, expected_revision=stopped['request_revision'],
                config={'max_simulations': 999999, 'max_runtime_seconds': 999999,
                        'max_recoveries': 999999}, spawn_runner=self.spawn)
        self.assertEqual(resumed['authority'], group['authority'])
        self.assertEqual(len(self.spawned), 2)
        for lane in group['lanes']:
            member = self.paths.run_root / lane['run_id']
            control = read_runtime_control(member)
            self.assertEqual(control['max_simulations'], 4000)
            self.assertEqual(control['max_runtime_seconds'], 3600)
            self.assertEqual(control['max_recoveries'], 3)
            self.assertEqual(read_daily_budget(member)['remaining'], 3993)
        control = read_runtime_control(run)
        self.assertEqual(control['elapsed_seconds'], 123)
        self.assertEqual(control['recoveries_used'], 2)

    def test_stop_during_spawn_fences_remaining_lanes_and_stale_start(self):
        from wqb.research_group_driver import initialize_group_runtime, start_group_workers
        group = self.prepared(2)
        initialize_group_runtime(self.paths, group)
        def stop_after_spawn(argv, **kwargs):
            """Input: spawn args. Output: fake process after a concurrent durable Stop."""
            process = self.spawn(argv, **kwargs)
            current = read_group(Path(group['group_dir']))
            stop_group(Path(group['group_dir']), current['request_revision'])
            return process
        result = start_group_workers(self.paths, group, expected_revision=group['request_revision'],
            config={}, spawn_runner=stop_after_spawn)
        self.assertEqual(result['desired_state'], 'paused')
        self.assertEqual(len(self.spawned), 1)
        with self.assertRaises(ValueError):
            start_group_workers(self.paths, group, expected_revision=group['request_revision'], config={}, spawn_runner=self.spawn)

    def test_unrelated_active_legacy_is_refused_and_not_rotated(self):
        from wqb.research_group_driver import initialize_group_runtime
        group = self.prepared()
        pointer = dict(run_id='legacy', run_dir=str(self.paths.run_root / 'legacy'))
        _write(self.paths.run_root / 'active_run.json', pointer)
        before = (self.paths.run_root / 'active_run.json').read_bytes()
        with self.assertRaises(ValueError):
            initialize_group_runtime(self.paths, group)
        self.assertEqual(before, (self.paths.run_root / 'active_run.json').read_bytes())

    def test_frozen_source_tamper_rejected_before_start(self):
        from wqb.research_group_driver import initialize_group_runtime, start_group_workers
        group = self.prepared()
        initialize_group_runtime(self.paths, group)
        raw = self.paths.knowledge_root / next(iter(self.fixture.resources['source_texts']))
        raw.write_text('tampered', encoding='utf-8')
        with self.assertRaises(ValueError):
            start_group_workers(self.paths, group, expected_revision=group['request_revision'], config={}, spawn_runner=self.spawn)
        self.assertEqual(self.spawned, [])
        self.assertEqual(read_group(Path(group['group_dir']))['desired_state'], 'paused')

    def test_secret_filter_and_false_live_ceiling(self):
        from wqb.research_group_driver import initialize_group_runtime, start_group_workers
        group = self.prepared(live=False)
        initialize_group_runtime(self.paths, group)
        start_group_workers(self.paths, group, expected_revision=group['request_revision'], config={
            'password': 'NEVER_COPY', 'api_key': 'NEVER_COPY', 'ai_executor_argv': ['NEVER_COPY'],
            'request_timeout_seconds': 12, 'enable_live_api': True}, spawn_runner=self.spawn)
        run = self.paths.run_root / 'lane-0'
        self.assertFalse(read_runtime_control(run)['enable_live_api'])
        for path in (run / 'runtime/group_workers').rglob('*.json'):
            self.assertNotIn('NEVER_COPY', path.read_text())
        self.assertNotIn('NEVER_COPY', str(self.spawned))

    def test_start_n_lanes_uses_one_daily_pool(self):
        from wqb.research_group_driver import start_group_workers
        for count in (1, 2, 4):
            with self.subTest(count=count):
                if count != 1:
                    self.setUp()
                group = self.prepared(count)
                result = start_group_workers(self.paths, group, expected_revision=group['request_revision'],
                    config={}, spawn_runner=self.spawn)
                self.assertEqual(len(result['workers']), count)
                self.assertEqual(len(self.spawned), count)
                run = self.paths.run_root / 'lane-0'
                charge_daily_budget(run, 7, 'shared-charge')
                for lane in group['lanes']:
                    self.assertEqual(read_daily_budget(self.paths.run_root / lane['run_id'])['remaining'], 3993)

    def test_stale_start_does_not_initialize_authority(self):
        from wqb.research_group_driver import start_group_workers
        group = self.prepared()
        stop_group(Path(group['group_dir']), group['request_revision'])
        with self.assertRaises(ValueError):
            start_group_workers(self.paths, group, expected_revision=group['request_revision'],
                config={}, spawn_runner=self.spawn)
        self.assertFalse((self.paths.run_root / 'lane-0/runtime_control.json').exists())
        self.assertFalse((self.paths.run_root / 'active_research_group.json').exists())

    def test_frozen_worker_command_is_allowlisted_and_normalized(self):
        from wqb.research_group_driver import start_group_workers
        group = self.prepared()
        with patch('sys.frozen', True, create=True):
            start_group_workers(self.paths, group, expected_revision=group['request_revision'],
                config={}, spawn_runner=self.spawn)
        argv = self.spawned[0][0]
        self.assertEqual(argv[1:3], ['--worker-module', 'wqb.research_group_driver'])
        self.assertNotIn('-m', argv)

    def test_old_launch_cannot_enter_after_stop_and_new_start(self):
        from wqb.research_group_driver import main, start_group_workers
        group = self.prepared()
        def lost_ack(argv, **kwargs):
            """Input: process arguments. Output: uncertain launch exception after capture."""
            self.spawn(argv, **kwargs)
            raise OSError('unknown spawn result')
        started = start_group_workers(self.paths, group, expected_revision=group['request_revision'],
            config={}, spawn_runner=lost_ack)
        stopped = stop_group(Path(group['group_dir']), started['request_revision'])
        # An uncertain old launch remains owned, but never becomes a new launch.
        resumed = start_group_workers(self.paths, group, expected_revision=stopped['request_revision'],
            config={}, spawn_runner=self.spawn)
        self.assertEqual(len(self.spawned), 1)
        with patch('wqb.research_group_driver.run_group_lane') as lane_runner:
            with self.assertRaises(ValueError):
                main(self.spawned[0][0][3:])
            lane_runner.assert_not_called()
        self.assertEqual(resumed['desired_state'], 'running')

    def test_cancelled_before_spawn_can_start_only_after_new_human_revision(self):
        from wqb.research_group_driver import start_group_workers
        group = self.prepared()

        def stop_before_spawn(argv):
            """Input: worker argv list. Output: unchanged argv after durable Stop, before Popen."""
            current = read_group(Path(group['group_dir']))
            stop_group(Path(group['group_dir']), current['request_revision'])
            return argv

        with patch('wqb.desktop_application.packaged_worker_command', side_effect=stop_before_spawn):
            cancelled = start_group_workers(self.paths, group, expected_revision=group['request_revision'],
                config={}, spawn_runner=self.spawn)
        self.assertEqual(cancelled['workers'][0]['status'], 'cancelled')
        self.assertEqual(self.spawned, [])
        resumed = start_group_workers(self.paths, group, expected_revision=cancelled['request_revision'],
            config={}, spawn_runner=self.spawn)
        self.assertEqual(resumed['workers'][0]['status'], 'spawned')
        self.assertEqual(len(self.spawned), 1)

    def test_worker_callbacks_preserve_authenticated_tree_config(self):
        from wqb.research_group_driver import run_group_lane, initialize_group_runtime
        group = self.prepared()
        initialize_group_runtime(self.paths, group)
        run = self.paths.run_root / 'lane-0'
        authenticated = dict(active_workflow_run_dir=str(run), ai_plan_receipt='bound-plan',
            hypothesis_bindings=[{'tree': 'retained'}], hypothesis_snapshot={'frozen': True},
            tree_node_id='node-1')

        def auto(paths, config, now, **callbacks):
            """Input: ordinary auto-continue interface. Output: offline callback results."""
            self.assertEqual(config['bound_group_lane'], str(run))
            with self.assertRaisesRegex(ValueError, 'lane identity mismatch'):
                callbacks['source_batch_runner'](dict(authenticated,
                    active_workflow_run_dir=str(run.parent / 'other-lane')), {})
            callbacks['source_batch_runner'](authenticated, {'dataset_id': 'test'})
            callbacks['complete_in_flight_runner']('existing-source')
            callbacks['retry_planned_runner']('existing-source')
            return {'run_dir': str(run), 'next_action': 'offline-boundary'}

        def drive(paths, config, *, step):
            """Input: existing driver inputs. Output: one isolated callback step."""
            self.assertEqual(config['bound_group_lane'], str(run))
            return step()

        with patch('wqb.workflow_driver.run_workflow_driver', side_effect=drive), \
                patch('wqb.workflow_auto_continue.auto_continue_workflow', side_effect=auto), \
                patch('wqb.cli.field_batch', return_value={}) as source, \
                patch('wqb.cli.complete_in_flight') as complete, \
                patch('wqb.cli.retry_planned') as retry, \
                patch('wqb.cli.summarize_run_dir', return_value={}), \
                patch('wqb.research_planning.prepare_source_plan', side_effect=AssertionError('must not replace tree')):
            run_group_lane(self.paths, group, run, config={})
        self.assertIs(source.call_args.args[0], authenticated)
        self.assertEqual(complete.call_args.args[0]['bound_group_lane'], str(run))
        self.assertEqual(retry.call_args.args[0]['bound_group_lane'], str(run))
        self.assertEqual(retry.call_args.args[0]['run_root'], str(self.paths.run_root))

    def test_false_live_authority_never_installs_transport_callbacks(self):
        from wqb.research_group_driver import initialize_group_runtime, run_group_lane
        group = self.prepared(live=False)
        initialize_group_runtime(self.paths, group)
        run = self.paths.run_root / 'lane-0'

        def auto(paths, config, now, **callbacks):
            """Input: auto-continue inputs. Output: offline result after checking transport isolation."""
            self.assertFalse(callbacks['enable_live_api'])
            for name in ('source_batch_runner', 'complete_in_flight_runner',
                         'retry_planned_runner', 'repair_executor'):
                self.assertIsNone(callbacks[name])
            return {'run_dir': str(run), 'next_action': 'enable-live-api-required'}

        def drive(paths, config, *, step):
            """Input: ordinary driver inputs. Output: one fake step without worker execution."""
            return step()

        with patch('wqb.workflow_driver.run_workflow_driver', side_effect=drive), \
                patch('wqb.workflow_auto_continue.auto_continue_workflow', side_effect=auto), \
                patch('wqb.repair_runtime.RepairRuntimeExecutor') as repair:
            run_group_lane(self.paths, group, run, config={'enable_live_api': True})
        repair.assert_not_called()

    def test_real_driver_status_is_lane_bound_and_paused_group_never_steps(self):
        from wqb.research_group_driver import run_group_lane, initialize_group_runtime
        group = self.prepared(2)
        initialize_group_runtime(self.paths, group)
        run = self.paths.run_root / 'lane-1'
        with patch('wqb.orchestrator.WorkflowOrchestrator', wraps=WorkflowOrchestrator) as orchestrator:
            result = run_group_lane(self.paths, group, run, config={},
                step=lambda: self.fail('paused group must not execute'))
        self.assertEqual(orchestrator.call_args.kwargs['bound_run_dir'], run)
        self.assertEqual(result['runtime_status'], 'paused')
        self.assertEqual(Path(result['run_dir']), run)

    def test_real_auto_continue_step_only_advances_bound_lane_offline(self):
        from wqb.research_group_driver import initialize_group_runtime, run_group_lane
        group = self.prepared(2, live=False)
        initialize_group_runtime(self.paths, group)
        run = self.paths.run_root / 'lane-1'

        def one_step(paths, config, *, step):
            """Input: ordinary driver inputs. Output: one real local-only step, no scheduler loop."""
            return step()

        with patch('wqb.workflow_driver.run_workflow_driver', side_effect=one_step), \
                patch('wqb.research_planning.prepare_source_plan', side_effect=AssertionError('no model plan')):
            result = run_group_lane(self.paths, group, run, config={})
        self.assertEqual(Path(result['run_dir']), run)
        self.assertEqual(result['current_stage'], 'schedule')
        self.assertEqual(json.loads((run / 'run_state.json').read_text())['current_stage'], 'schedule')
        self.assertFalse((self.paths.run_root / 'lane-0/stages').exists())
        self.assertFalse((self.paths.run_root / 'active_run.json').exists())

    def test_recorded_worker_entry_persists_result_and_cannot_be_reentered(self):
        from wqb.research_group_driver import main, start_group_workers
        group = self.prepared()
        started = start_group_workers(self.paths, group, expected_revision=group['request_revision'],
            config={}, spawn_runner=self.spawn)
        worker = started['workers'][0]
        args = self.spawned[0][0][3:]
        with patch('wqb.research_group_driver.run_group_lane', return_value={'runtime_status': 'paused'}) as lane:
            self.assertEqual(main(args), 0)
            with self.assertRaises(ValueError):
                main(args)
            self.assertEqual(lane.call_count, 1)
        job = Path(worker['evidence_dir'])
        self.assertEqual(json.loads((job / 'result.json').read_text())['runtime_status'], 'paused')
        self.assertEqual(json.loads((job / 'job.json').read_text())['status'], 'exited')


if __name__ == '__main__':
    unittest.main()
