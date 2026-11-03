"""Offline lifecycle tests with real frozen contexts, accounting and fake processes."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
import threading
import time
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
        with patch('wqb.research_group_driver.supervise_group_lane', return_value={'runtime_status': 'paused'}) as lane:
            self.assertEqual(main(args), 0)
            with self.assertRaises(ValueError):
                main(args)
            self.assertEqual(lane.call_count, 1)
        job = Path(worker['evidence_dir'])
        self.assertEqual(json.loads((job / 'result.json').read_text())['runtime_status'], 'paused')
        self.assertEqual(json.loads((job / 'job.json').read_text())['status'], 'exited')

    def supervise(self, mode='timeout', confirmed=True):
        """Input: fake completion mode str/confirmation bool. Output: supervisor result and fake tree; no real transport."""
        from wqb import research_group_driver as driver
        group = self.prepared()
        started = driver.start_group_workers(self.paths, group, expected_revision=group['request_revision'],
            config={'request_timeout_seconds': 2}, spawn_runner=self.spawn)
        run = self.paths.run_root / 'lane-0'
        worker = {**started['workers'][0], 'status': 'running', 'pid': os.getpid()}
        _write(run / 'runtime/group_worker.json', worker)
        job = Path(worker['evidence_dir'])
        self.addCleanup(driver._UNCONFIRMED_OWNERS.pop, str(job), None)
        if mode == 'runtime-expiry':
            update_runtime_status(run, elapsed_seconds=3598)
        clock = [100.0]
        child = SimpleNamespace(pid=800123, returncode=None)
        tree = SimpleNamespace(spawn_kwargs={}, stopped=False, closed=False, observations=[])
        def attach(process):
            """Input: retained fake process. Output: None; bind only the actual returned handle."""
            self.assertIs(process, child)
        tree.attach = attach
        def poll():
            """Input: none. Output: fake process exit code without PID lookup."""
            return child.returncode
        tree.poll = poll
        def terminate():
            """Input: none. Output: bool; simulate a response racing process termination."""
            tree.stopped = True
            if mode == 'lease-replaced':
                _write(run / 'runtime/source_run_lock.json', dict(status='running', pid=child.pid,
                    owner_id='replacement-owner', action='workflow-driver'))
            if mode == 'termination-error':
                raise OSError('private termination diagnostic')
            if mode == 'late-response':
                row = json.loads((job / 'network_current.json').read_text())
                _write(job / 'network_current.json', {**row, 'state': 'completed', 'response_recorded': True})
                from wqb.research_group import record_payload_outcome
                record_payload_outcome(run, row['simulation_identities'],
                    SimpleNamespace(status_code=201, headers={'Location': 'https://fixture/simulations/known'}))
            child.returncode = -9
            tree.observations.append(json.loads((run / 'runtime/source_run_lock.json').read_text())['status'])
            return confirmed
        tree.terminate_and_confirm = terminate
        tree.close = lambda: setattr(tree, 'closed', True)
        identity = 'c' * 64
        def sleep(seconds):
            """Input: polling seconds float. Output: None; advance only a deterministic fake clock."""
            clock[0] += 1
            if not (job / 'network_current.json').exists():
                owner = json.loads((job / 'network_owner.json').read_text())
                _write(run / 'runtime/source_run_lock.json', dict(status='running', pid=child.pid,
                    owner_id='fake-lock-owner', action='workflow-driver'))
                row = dict(request_id='d' * 32, owner_nonce=owner['owner_nonce'],
                    execution_pid=child.pid, supervisor_pid=os.getpid(), method='POST',
                    operation='simulation_submit', simulation_identities=[identity],
                    state='entered', started=clock[0], deadline=clock[0] + 2)
                if mode == 'runtime-expiry':
                    row['deadline'] = owner['runtime_deadline']
                from wqb.research_group import _reserve_identities
                _reserve_identities(Path(group['group_dir']), run.name, [identity], submission=True)
                charge_daily_budget(run, 1, 'offline-owned-request')
                update_runtime_status(run, elapsed_seconds=17)
                if mode == 'nonce-mismatch':
                    row['owner_nonce'] = 'e' * 32
                if mode == 'pid-reuse':
                    row['execution_pid'] = 999999
                if mode == 'corrupt-deadline':
                    row['deadline'] = float('nan')
                if mode == 'future-start':
                    row['started'] += 50
                    row['deadline'] += 50
                _write(job / 'network_current.json', row)
                if mode == 'stop':
                    # Persist intent without waiting on the fake request's fence.
                    current = json.loads((Path(group['group_dir']) / 'group_intent.json').read_text())
                    _write(Path(group['group_dir']) / 'group_intent.json',
                        {**current, 'desired_state': 'paused', 'request_revision': 'f' * 32})
            elif mode == 'completion-race' and clock[0] >= 103:
                row = json.loads((job / 'network_current.json').read_text())
                _write(job / 'network_current.json', {**row, 'state': 'completed'})
                owner = json.loads((job / 'network_owner.json').read_text())
                _write(job / 'execution_result.json', {'owner_nonce': owner['owner_nonce'],
                    'result': {'runtime_status': 'paused'}})
                child.returncode = 0
        read_record = driver._read
        raced = False
        def read(path):
            """Input: JSON Path. Output: dict; publish once during a read using only the injected clock."""
            nonlocal raced
            if (mode in {'read-race', 'future-read'} and path == job / 'network_current.json'
                    and not raced):
                raced = True
                clock[0] += .25
                row = read_record(path)
                started = clock[0] + (50 if mode == 'future-read' else 0)
                _write(path, {**row, 'started': started, 'deadline': started + 2})
            return read_record(path)
        with patch.object(driver, 'OwnedExecutionTree', return_value=tree), \
                patch.object(driver, '_read', side_effect=read), \
                patch('wqb.maintenance_notifications.dispatch_notification', side_effect=lambda r, c, n: c):
            result = driver.supervise_group_lane(self.paths, group, run, config={'request_timeout_seconds': 2},
                spawn_runner=lambda *a, **k: child, now_func=lambda: clock[0], sleep_func=sleep)
        return result, tree, run, job

    def test_request_published_during_read_reaches_its_total_deadline(self):
        result, tree, run, job = self.supervise('read-race')
        self.assertEqual(result['runtime_reason'], 'network_total_deadline_exceeded')
        self.assertTrue(result['termination_confirmed'])
        self.assertEqual(result['request_outcome'], 'unknown')
        self.assertEqual(read_daily_budget(run)['lifetime_attempts'], 1)

    def test_request_still_in_future_after_read_is_rejected_by_injected_clock(self):
        result, tree, run, job = self.supervise('future-read')
        self.assertEqual(result['runtime_reason'], 'owned_network_request_invalid')
        self.assertTrue(result['termination_confirmed'])
        self.assertEqual(read_daily_budget(run)['lifetime_attempts'], 1)

    def test_pid_reuse_cannot_release_a_replaced_source_lease(self):
        result, tree, run, job = self.supervise('lease-replaced')
        self.assertTrue(result['termination_confirmed'])
        lock = json.loads((run / 'runtime/source_run_lock.json').read_text())
        self.assertEqual(lock['status'], 'running')
        self.assertEqual(lock['owner_id'], 'replacement-owner')

    def test_termination_error_is_sanitized_and_keeps_ownership_quarantined(self):
        result, tree, run, job = self.supervise('termination-error')
        self.assertFalse(result['termination_confirmed'])
        self.assertEqual(result['runtime_reason'], 'owned_network_termination_unconfirmed')
        self.assertNotIn('private termination diagnostic', (job / 'network_supervision.json').read_text())

    def test_execute_role_does_not_persist_exception_urls_or_payloads(self):
        from wqb import research_group_driver as driver
        group = self.prepared()
        driver.start_group_workers(self.paths, group, expected_revision=group['request_revision'],
            config={}, spawn_runner=self.spawn)
        args = ['execute', *self.spawned[0][0][4:]]
        with patch.object(driver, '_execute_owned_lane', side_effect=RuntimeError('https://private?secret=payload')):
            self.assertEqual(driver.main(args), 1)

    def test_request_deadline_never_extends_remaining_original_runtime(self):
        result, tree, run, job = self.supervise('runtime-expiry')
        self.assertEqual(result['runtime_reason'], 'runtime_budget_exhausted')
        self.assertEqual(result['request_outcome'], 'unknown')
        self.assertGreaterEqual(read_runtime_control(run)['elapsed_seconds'], 3600)
        self.assertEqual(read_runtime_control(run)['max_runtime_seconds'], 3600)
        self.assertEqual(read_daily_budget(run)['lifetime_attempts'], 1)

    def test_owned_total_timeout_terminates_before_releasing_source_lease(self):
        result, tree, run, job = self.supervise()
        self.assertEqual(result['runtime_reason'], 'network_total_deadline_exceeded')
        self.assertTrue(result['termination_confirmed'])
        self.assertTrue(tree.stopped)
        self.assertEqual(tree.observations, ['running'])
        self.assertEqual(json.loads((run / 'runtime/source_run_lock.json').read_text())['status'], 'released')
        self.assertEqual(result['request_outcome'], 'unknown')
        self.assertEqual(read_daily_budget(run)['lifetime_attempts'], 1)
        claims = json.loads((run.parent / 'research_groups/simulation_reservations.json').read_text())
        self.assertEqual(claims['c' * 64]['submission_status'], 'unknown')

    def test_unconfirmed_termination_never_releases_source_lease(self):
        result, tree, run, job = self.supervise(confirmed=False)
        self.assertFalse(result['termination_confirmed'])
        self.assertEqual(result['runtime_reason'], 'owned_network_termination_unconfirmed')
        self.assertEqual(json.loads((run / 'runtime/source_run_lock.json').read_text())['status'], 'running')

    def test_deadline_completion_race_keeps_completed_response(self):
        result, tree, run, job = self.supervise('completion-race')
        self.assertEqual(result['runtime_status'], 'paused')
        self.assertEqual(result.get('runtime_reason', ''), '')

    def test_request_pid_nonce_and_deadline_corruption_never_target_foreign_pid(self):
        for mode in ('pid-reuse', 'nonce-mismatch', 'corrupt-deadline', 'future-start'):
            with self.subTest(mode=mode):
                if mode != 'pid-reuse':
                    self.setUp()
                result, tree, run, job = self.supervise(mode)
                self.assertEqual(result['runtime_reason'], 'owned_network_request_invalid')
                self.assertTrue(tree.stopped)
                self.assertTrue(result['termination_confirmed'])

    def test_stop_during_post_preserves_unknown_and_original_authority(self):
        result, tree, run, job = self.supervise('stop')
        self.assertEqual(result['runtime_status'], 'paused')
        self.assertEqual(result['runtime_reason'], 'user_paused')
        self.assertEqual(result['request_outcome'], 'unknown')
        control = read_runtime_control(run)
        self.assertEqual(control['max_runtime_seconds'], 3600)
        self.assertEqual(control['max_recoveries'], 3)
        self.assertEqual(read_group(run.parent / 'research_groups' / json.loads(
            (run / 'research_group_binding.json').read_text())['group_id'])['desired_state'], 'paused')

    def test_late_response_is_reconciled_without_resubmit_or_refund(self):
        result, tree, run, job = self.supervise('late-response')
        self.assertEqual(result['request_outcome'], 'response_recorded_reconcile')
        claims = json.loads((run.parent / 'research_groups/simulation_reservations.json').read_text())
        self.assertEqual(claims['c' * 64]['progress_url'], 'https://fixture/simulations/known')
        self.assertNotIn('https://', (job / 'network_supervision.json').read_text())

    def local_trickle(self, stop=False, complete=False):
        """Input: Stop scenario bool. Output: result/evidence; real owned subprocesses, loopback HTTP only."""
        from wqb import research_group_driver as driver
        from wqb.submission_attempts import uncertain_submission_hashes
        entered = threading.Event()
        arrivals = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                """Input: server log args. Output: None; keep fictional HTTP logs quiet."""
            def do_POST(self):
                """Input: local HTTP request. Output: trickling body, always faster than the read inactivity timeout."""
                self.rfile.read(int(self.headers['Content-Length']))
                arrivals.append(time.monotonic())
                self.send_response(201)
                self.send_header('Content-Length', '200')
                self.send_header('Location', '/simulations/fixture-only')
                self.end_headers()
                entered.set()
                try:
                    if complete:
                        self.wfile.write(b'x' * 200)
                        self.wfile.flush()
                        return
                    for _ in range(200):
                        self.wfile.write(b'x')
                        self.wfile.flush()
                        time.sleep(.04)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        serving = threading.Thread(target=lambda: server.serve_forever(poll_interval=.02), daemon=True)
        serving.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        group = self.prepared()
        started = driver.start_group_workers(self.paths, group, expected_revision=group['request_revision'],
            config={'request_timeout_seconds': .6}, spawn_runner=self.spawn)
        run = self.paths.run_root / 'lane-0'
        worker = {**started['workers'][0], 'status': 'running', 'pid': os.getpid()}
        _write(run / 'runtime/group_worker.json', worker)
        job = Path(worker['evidence_dir'])
        stopped, errors = [], []
        confirmed_tree = threading.Event()
        def stop_when_entered():
            """Input: none. Output: None; real Stop must persist then wait until the sending fence is released."""
            if not entered.wait(10):
                errors.append('local POST did not enter')
                return
            try:
                stopped.append(stop_group(Path(group['group_dir']), started['request_revision']))
                if not confirmed_tree.is_set():
                    errors.append('Stop acknowledged before subtree termination was confirmed')
            except Exception as error:
                errors.append(repr(error))
        stopper = threading.Thread(target=stop_when_entered, daemon=True) if stop else None
        if stopper:
            stopper.start()
        processes = []
        def spawn(argv, **kwargs):
            """Input: real execution argv/kwargs. Output: real Popen with only fixture transport replacement."""
            self.assertEqual(argv[3], 'execute')
            script = ('import sys; from tests.test_owned_network_deadline import fixture_execution; '
                      'sys.exit(fixture_execution(sys.argv[1:]))')
            environment = {**kwargs.pop('env'), 'FIXTURE_HTTP': f'http://127.0.0.1:{server.server_port}'}
            process = subprocess.Popen([sys.executable, '-B', '-c', script, *argv[3:]], env=environment, **kwargs)
            processes.append(process)
            return process
        tree = driver.OwnedExecutionTree()
        terminate = tree.terminate_and_confirm
        def confirm():
            """Input: none. Output: bool; expose the interval between process death and confirmed tree cleanup."""
            result = terminate()
            time.sleep(.15)
            if result:
                confirmed_tree.set()
            return result
        tree.terminate_and_confirm = confirm
        with patch('wqb.maintenance_notifications.dispatch_notification', side_effect=lambda r, c, n: c), \
                patch.object(driver, 'OwnedExecutionTree', return_value=tree):
            result = driver.supervise_group_lane(self.paths, group, run,
                config={'request_timeout_seconds': .6}, spawn_runner=spawn)
        if stopper:
            stopper.join(10)
            self.assertFalse(stopper.is_alive())
            self.assertEqual(errors, [], (result, (job / 'execution.log').read_text()))
            self.assertEqual(stopped[0]['desired_state'], 'paused')
        self.assertTrue(entered.is_set(), (result, (job / 'execution.log').read_text()))
        self.assertEqual(len(arrivals), 1)
        self.assertLess(time.monotonic() - arrivals[0], 3)
        self.assertTrue(json.loads((job / 'network_supervision.json').read_text())['termination_confirmed'])
        self.assertIsNotNone(processes[0].poll())
        self.assertEqual(read_daily_budget(run)['lifetime_attempts'], 1)
        events = [json.loads(line) for line in (run / 'stages/offline-network/simulation_events.jsonl').read_text().splitlines()]
        self.assertEqual(len(uncertain_submission_hashes(events)), 0 if complete else 1)
        self.assertEqual(len(events), 2 if complete else 1)
        self.assertEqual(json.loads((run / 'runtime/source_run_lock.json').read_text())['status'], 'released')
        self.assertEqual(read_runtime_control(run)['max_runtime_seconds'], 3600)
        self.assertEqual(read_runtime_control(run)['max_recoveries'], 3)
        return result, run, job

    def test_actual_trickle_http_is_killed_at_total_deadline_and_unknown_post_is_not_replayed(self):
        result, run, job = self.local_trickle()
        self.assertEqual(result['runtime_reason'], 'network_total_deadline_exceeded')
        self.assertEqual(result['request_outcome'], 'unknown')
        from wqb.research_group import reserve_payloads
        with self.assertRaisesRegex(RuntimeError, 'already reserved or outcome unknown'):
            reserve_payloads(run, {'regular': 'rank(close)', 'settings': {}})
        with self.assertRaisesRegex(ValueError, 'cannot be replayed'):
            from wqb.research_group_driver import supervise_group_lane
            supervise_group_lane(self.paths,
                run.parent / 'research_groups' / json.loads((run / 'research_group_binding.json').read_text())['group_id'],
                run, config={})

    def test_actual_stop_during_trickle_post_acknowledges_only_after_owned_tree_dies(self):
        result, run, job = self.local_trickle(stop=True)
        self.assertEqual(result['runtime_status'], 'paused')
        self.assertEqual(result['runtime_reason'], 'user_paused')

    def test_actual_completed_post_retains_location_and_ordinary_driver_result(self):
        result, run, job = self.local_trickle(complete=True)
        self.assertEqual(result['runtime_status'], 'completed')
        claims = json.loads((run.parent / 'research_groups/simulation_reservations.json').read_text())
        self.assertEqual(list(claims.values())[0]['progress_url'], '/simulations/fixture-only')
        self.assertEqual(json.loads((job / 'network_current.json').read_text())['state'], 'completed')


if __name__ == '__main__':
    unittest.main()
