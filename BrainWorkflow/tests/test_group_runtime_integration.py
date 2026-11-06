"""Offline transport/driver tests for shared lane authority."""

from datetime import datetime, timedelta, timezone
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

from wqb.client import WQBClient
from wqb.research_group import create_group, resume_group, read_group
from wqb.runtime_control import (CONTROL_ENV, RuntimePaused, request_runtime_state,
                                 read_runtime_control, _write)
from wqb.simulator import submit_simulation, submit_multisimulation
from wqb.workflow_driver import run_workflow_driver


def running_group(root, count=2, live=True, recoveries=1):
    """Input: Path/int/bool/int. Output: group dict with offline child authority."""
    group = create_group(root, [dict(run_id=f'lane-{i}', plan_digest=str(i) * 64)
                               for i in range(count)],
                         dict(enable_live_api=live, max_runtime_seconds=3600,
                              max_recoveries=recoveries))
    for lane in group['lanes']:
        request_runtime_state(root / lane['run_id'], 'running', enable_live_api=True)
    return resume_group(Path(group['group_dir']), group['request_revision'])


def transport(status=201):
    """Input: HTTP status int. Output: authenticated fake client and session Mock."""
    session = Mock()
    response = requests.Response()
    response.status_code = status
    response._content = b'{}'
    response.headers.update(Location='/simulations/fake', **{'Retry-After': '0'} if status == 429 else {})
    session.request.return_value = response
    client = WQBClient(session=session)
    client.authenticated = True
    return client, session


def lane_process(root, index, ready, start, results, mode):
    """Input: root str/index int/IPC/mode str. Output: queue evidence from one isolated fake lane."""
    try:
        root = Path(root)
        lane = root / f'lane-{index}'
        os.environ[CONTROL_ENV] = str(lane)
        ready.put(index)
        if not start.wait(15):
            raise RuntimeError('test start barrier timed out')
        if mode == 'runenv':
            prior = str(root / 'prior-control')
            os.environ[CONTROL_ENV] = prior
            initial = dict(active=True, run_dir=str(lane), status='running')
            observed = []
            def step():
                """Input: none. Output: completed dict, capturing actual driver child environment."""
                observed.append(os.environ[CONTROL_ENV])
                return {**initial, 'status': 'completed'}
            result = run_workflow_driver(SimpleNamespace(run_root=root), {'bound_group_lane': str(lane)},
                                         step=step, status_reader=lambda: initial)
            results.put((index, result['runtime_status'], observed[0], os.environ[CONTROL_ENV] == prior))
        elif mode == 'recovery':
            from wqb.research_group import authorize_group_retry
            source = root / f'source-{index}'
            now = datetime.now(timezone.utc).isoformat()
            _write(source / 'rate_limit_state.json', dict(status='cooldown', retry_at=now,
                updated_at=now, attempt_count=3, consecutive_429_count=3))
            authorize_group_retry(lane, source, now)
            results.put((index, 'leased', os.environ[CONTROL_ENV]))
        else:
            client, session = transport()
            submit_simulation(client, dict(regular='rank(close)', settings={}))
            results.put((index, 'sent', os.environ[CONTROL_ENV], session.request.call_count))
    except RuntimePaused as error:
        results.put((index, str(error), os.environ.get(CONTROL_ENV)))
    except Exception as error:
        results.put((index, 'ERROR', repr(error)))


def held_post_process(root, entered, release, results):
    """Input: root str and IPC. Output: one fake POST held across another process's Stop request."""
    os.environ[CONTROL_ENV] = str(Path(root) / 'lane-0')
    client, session = transport()
    response = session.request.return_value
    def dispatch(*args, **kwargs):
        """Input: fake transport arguments. Output: response after test-controlled release."""
        entered.set()
        if not release.wait(15):
            raise RuntimeError('test POST release timeout')
        return response
    session.request.side_effect = dispatch
    try:
        results.put(submit_simulation(client, dict(regular='rank(close)', settings={})))
    except Exception as error:
        results.put(repr(error))


class GroupRuntimeIntegrationTests(unittest.TestCase):
    def test_multiprocess_n1_n2_n4_dedup_recovery_pause_deadline_and_runenv(self):
        from wqb.research_group import stop_group
        ctx = multiprocessing.get_context('spawn')
        for count in (1, 2, 4):
            for mode in ('dedup', 'recovery', 'pause', 'deadline', 'runenv'):
                with self.subTest(count=count, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    group = running_group(root, count=count, recoveries=1)
                    path = Path(group['group_dir'])
                    ready, results, start = ctx.Queue(), ctx.Queue(), ctx.Event()
                    workers = [ctx.Process(target=lane_process,
                               args=(str(root), i, ready, start, results, mode)) for i in range(count)]
                    try:
                        for worker in workers:
                            worker.start()
                        for _ in workers:
                            ready.get(timeout=20)
                        if mode == 'pause':
                            stop_group(path, group['request_revision'])
                        if mode == 'deadline':
                            intent = json.loads((path / 'group_intent.json').read_text())
                            _write(path / 'group_intent.json', {**intent, 'elapsed_seconds': 3600})
                        start.set()
                        rows = [results.get(timeout=20) for _ in workers]
                        for worker in workers:
                            worker.join(20)
                            self.assertEqual(worker.exitcode, 0)
                        self.assertFalse(any(row[1] == 'ERROR' for row in rows), rows)
                        for row in rows:
                            self.assertEqual(Path(row[2]), root / f'lane-{row[0]}')
                        if mode == 'dedup':
                            self.assertEqual(sum(row[1] == 'sent' for row in rows), 1, rows)
                            self.assertEqual(sum(read_runtime_control(root / f'lane-{i}').get(
                                'simulation_attempts', 0) for i in range(count)), 1)
                        elif mode == 'recovery':
                            self.assertEqual(sum(row[1] == 'leased' for row in rows), 1, rows)
                            self.assertEqual(read_group(path)['recoveries_used'], 1)
                        elif mode == 'runenv':
                            self.assertTrue(all(row[1] == 'completed' and row[3] for row in rows), rows)
                        else:
                            self.assertTrue(all(('paused' if mode == 'pause' else 'budget exhausted')
                                                in row[1] for row in rows), rows)
                    finally:
                        start.set()
                        for worker in workers:
                            if worker.is_alive():
                                worker.terminate()
                            worker.join(5)
                        ready.close()
                        results.close()

    def test_multiprocess_stop_persists_before_waiting_for_actual_post_fence(self):
        from wqb.research_group import stop_group
        ctx = multiprocessing.get_context('spawn')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = running_group(root)
            path = Path(group['group_dir'])
            entered, release, results = ctx.Event(), ctx.Event(), ctx.Queue()
            worker = ctx.Process(target=held_post_process, args=(str(root), entered, release, results))
            stopped, errors = threading.Event(), []
            def stop():
                """Input: none. Output: None; retain Stop completion/error evidence for parent assertions."""
                try:
                    stop_group(path, group['request_revision'])
                    stopped.set()
                except Exception as error:
                    errors.append(error)
            stopper = threading.Thread(target=stop)
            try:
                worker.start()
                self.assertTrue(entered.wait(20))
                stopper.start()
                deadline = time.monotonic() + 5
                while read_group(path)['desired_state'] != 'paused' and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(read_group(path)['desired_state'], 'paused')
                self.assertFalse(stopped.is_set())
                other, session = transport()
                with patch.dict(os.environ, {CONTROL_ENV: str(root / 'lane-1')}):
                    with self.assertRaisesRegex(RuntimePaused, 'paused'):
                        submit_simulation(other, dict(regular='rank(volume)', settings={}))
                session.request.assert_not_called()
                release.set()
                worker.join(20)
                stopper.join(20)
                self.assertEqual(worker.exitcode, 0)
                self.assertEqual(results.get(timeout=5), '/simulations/fake')
                self.assertTrue(stopped.is_set(), errors)
                self.assertFalse(errors)
            finally:
                release.set()
                if worker.is_alive():
                    worker.terminate()
                worker.join(5)
                if stopper.ident is not None:
                    stopper.join(5)
                results.close()

    def test_expired_cooldown_get_retains_threshold_and_post_requires_lease(self):
        from wqb.rate_limit_state import RateLimitRecoveryRequired
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            running_group(root)
            source = root / 'research_groups/account_cooldown'
            now = datetime.now(timezone.utc) - timedelta(seconds=5)
            _write(source / 'rate_limit_state.json', dict(status='cooldown', retry_at=now.isoformat(),
                updated_at=now.isoformat(), attempt_count=2, consecutive_429_count=2))
            client, session = transport()
            with patch.dict(os.environ, {CONTROL_ENV: str(root / 'lane-0')}):
                self.assertEqual(client.request('GET', '/simulations/existing').status_code, 201)
                with self.assertRaises(RateLimitRecoveryRequired):
                    submit_simulation(client, dict(regular='rank(close)', settings={}))
            self.assertEqual(session.request.call_count, 1)

    def test_accepted_post_resets_only_its_unchanged_shared_cooldown(self):
        from wqb.research_group import authorize_group_retry
        from wqb.rate_limit_state import read_rate_limit_state
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            running_group(root)
            lane = root / 'lane-0'
            source = root / 'research_groups/account_cooldown'
            now = datetime.now(timezone.utc)
            _write(source / 'rate_limit_state.json', dict(status='cooldown',
                retry_at=(now - timedelta(seconds=1)).isoformat(), updated_at=now.isoformat(),
                attempt_count=3, consecutive_429_count=3))
            authorize_group_retry(lane, source, now.isoformat())
            client, _ = transport()
            with patch.dict(os.environ, {CONTROL_ENV: str(lane)}):
                submit_simulation(client, dict(regular='rank(close)', settings={}))
            self.assertEqual(read_rate_limit_state(source / 'rate_limit_state.json')['status'], 'ready')

    def test_authentication_429_is_shared_and_not_retried_in_client(self):
        from wqb.rate_limit_state import RateLimitRecoveryRequired
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            running_group(root)
            client, session = transport(429)
            client.authenticated = False
            session.post.return_value = session.request.return_value
            with patch('wqb.client.load_credentials', return_value=('fixture', 'fixture')):
                with patch.dict(os.environ, {CONTROL_ENV: str(root / 'lane-0')}):
                    with self.assertRaises(RateLimitRecoveryRequired):
                        client.request('GET', '/simulations/existing')
            self.assertEqual(session.post.call_count, 1)
            session.request.assert_not_called()

    def test_validated_get_progress_resets_cooldown_but_invalid_json_does_not(self):
        from wqb.research_group import authorize_group_retry
        from wqb.rate_limit_state import read_rate_limit_state
        for valid in (True, False):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                running_group(root)
                lane = root / 'lane-0'
                source = root / 'research_groups/account_cooldown'
                now = datetime.now(timezone.utc).isoformat()
                _write(source / 'rate_limit_state.json', dict(status='cooldown',
                    retry_at=now, updated_at=now, attempt_count=3, consecutive_429_count=3))
                authorize_group_retry(lane, source, now)
                client, session = transport(200)
                if not valid:
                    session.request.return_value._content = b'not json'
                with patch.dict(os.environ, {CONTROL_ENV: str(lane)}):
                    if valid:
                        self.assertEqual(client.get_json('/alphas/existing/check'), {})
                    else:
                        with self.assertRaises(requests.exceptions.JSONDecodeError):
                            client.get_json('/alphas/existing/check')
                self.assertEqual(read_rate_limit_state(source / 'rate_limit_state.json')['status'],
                                 'ready' if valid else 'cooldown')

    def test_inflight_progress_cannot_clear_newer_account_429(self):
        from wqb.research_group import record_account_progress, record_account_429
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            running_group(root)
            lane = root / 'lane-0'
            source = root / 'research_groups/account_cooldown'
            now = datetime.now(timezone.utc).isoformat()
            prior = dict(status='cooldown', retry_at=now, updated_at=now,
                         attempt_count=1, consecutive_429_count=1)
            _write(source / 'rate_limit_state.json', prior)
            client, session = transport(429)
            record_account_429(root / 'lane-1', session.request.return_value, 'GET')
            record_account_progress(lane, prior, 'fixture_accepted_progress')
            state = json.loads((source / 'rate_limit_state.json').read_text())
            self.assertEqual(state['status'], 'cooldown')
            self.assertEqual(state['consecutive_429_count'], 2)

    def test_known_429_can_retry_after_wait_but_unknown_500_cannot(self):
        for status in (429, 503):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                running_group(root)
                client, session = transport(status)
                payload = dict(regular='rank(close)', settings={})
                with patch.dict(os.environ, {CONTROL_ENV: str(root / 'lane-0')}):
                    with self.assertRaises(requests.HTTPError if status == 429 else RuntimeError):
                        submit_simulation(client, payload)
                    session.request.return_value.status_code = 201
                    if status == 429:
                        self.assertEqual(submit_simulation(client, payload), '/simulations/fake')
                    else:
                        with self.assertRaisesRegex(RuntimePaused, 'identity'):
                            submit_simulation(client, payload)
                self.assertEqual(session.request.call_count, 2 if status == 429 else 1)

    def test_pre_dispatch_budget_refusal_does_not_quarantine_unsent_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            running_group(root)
            lane = root / 'lane-0'
            request_runtime_state(lane, 'running', max_simulations=1)
            client, session = transport()
            with patch.dict(os.environ, {CONTROL_ENV: str(lane)}):
                submit_simulation(client, dict(regular='rank(close)', settings={}))
                payload = dict(regular='rank(volume)', settings={})
                with self.assertRaisesRegex(RuntimePaused, 'attempt budget'):
                    submit_simulation(client, payload)
                # Explicit offline fixture authority, not an automatic production renewal.
                request_runtime_state(lane, 'running', max_simulations=2)
                self.assertEqual(submit_simulation(client, payload), '/simulations/fake')
            self.assertEqual(session.request.call_count, 2)

    def test_no_live_group_cannot_authenticate_before_permission_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            running_group(root, live=False)
            client, session = transport()
            client.authenticated = False
            with patch.object(client, 'authenticate') as authenticate:
                with patch.dict(os.environ, {CONTROL_ENV: str(root / 'lane-0')}):
                    with self.assertRaises(RuntimePaused):
                        client.request('GET', '/simulations/existing')
            authenticate.assert_not_called()

    def test_driver_default_status_reader_is_lane_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            lane = Path(tmp) / 'lane'
            orch = Mock()
            orch.status.return_value = dict(active=False)
            with patch('wqb.orchestrator.WorkflowOrchestrator', return_value=orch) as factory:
                run_workflow_driver(SimpleNamespace(), {'bound_group_lane': str(lane)}, step=Mock())
            self.assertEqual(factory.call_args.kwargs.get('bound_run_dir'), lane)

    def test_foreign_result_is_rejected_before_checkpoint_or_status_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            running_group(root)
            lane = root / 'lane-0'
            initial = dict(active=True, run_dir=str(lane), status='running')
            foreign = {**initial, 'run_dir': str(root / 'lane-1'), 'status': 'completed'}
            with patch('wqb.workflow_driver.schedule_run_checkpoint') as checkpoint:
                with self.assertRaisesRegex(ValueError, 'lane|run.*identity'):
                    run_workflow_driver(SimpleNamespace(run_root=root), {'bound_group_lane': str(lane)},
                                        step=lambda: foreign, status_reader=lambda: initial)
            checkpoint.assert_not_called()
            self.assertNotIn('last_result', read_runtime_control(lane))

    def test_group_live_ceiling_blocks_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            running_group(root, live=False)
            client, session = transport()
            with patch.dict(os.environ, {CONTROL_ENV: str(root / 'lane-0')}):
                with self.assertRaisesRegex(RuntimePaused, 'live.*permission'):
                    submit_simulation(client, {'regular': 'rank(close)', 'settings': {}})
            session.request.assert_not_called()

    def test_actual_post_is_deduplicated_for_owner_and_other_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            running_group(root)
            client, session = transport()
            payload = dict(regular='rank(close)', settings={'decay': 2})
            with patch.dict(os.environ, {CONTROL_ENV: str(root / 'lane-0')}):
                self.assertEqual(submit_simulation(client, payload), '/simulations/fake')
                with self.assertRaisesRegex(RuntimePaused, 'identity'):
                    submit_simulation(client, payload)
            with patch.dict(os.environ, {CONTROL_ENV: str(root / 'lane-1')}):
                with self.assertRaisesRegex(RuntimePaused, 'identity'):
                    submit_multisimulation(client, [payload])
            self.assertEqual(session.request.call_count, 1)
            self.assertEqual(read_runtime_control(root / 'lane-0')['simulation_attempts'], 1)
            self.assertEqual(read_runtime_control(root / 'lane-1').get('simulation_attempts', 0), 0)
            from wqb.cli import simulation_identity_hash
            claims = json.loads((root / 'research_groups/simulation_reservations.json').read_text())
            self.assertIn(simulation_identity_hash(payload['regular'], payload['settings']), claims)

    def test_unknown_post_survives_new_client_without_resubmit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            running_group(root)
            client, session = transport()
            session.request.side_effect = requests.Timeout('unknown')
            payload = dict(regular='rank(close)', settings={})
            with patch.dict(os.environ, {CONTROL_ENV: str(root / 'lane-0')}):
                with self.assertRaisesRegex(RuntimeError, 'outcome unknown'):
                    submit_simulation(client, payload)
                other, other_session = transport()
                with self.assertRaisesRegex(RuntimePaused, 'identity'):
                    submit_simulation(other, payload)
            other_session.request.assert_not_called()

    def test_actual_429_stops_other_lane_get_without_hidden_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            running_group(root)
            client, session = transport(429)
            session.request.return_value.headers['Retry-After'] = '30'
            with patch.dict(os.environ, {CONTROL_ENV: str(root / 'lane-0')}):
                with self.assertRaises(requests.HTTPError):
                    submit_simulation(client, dict(regular='rank(close)', settings={}))
            other, other_session = transport()
            from wqb.rate_limit_state import RateLimitRecoveryRequired
            with patch.dict(os.environ, {CONTROL_ENV: str(root / 'lane-1')}):
                with self.assertRaises(RateLimitRecoveryRequired):
                    other.get_json('/simulations/existing')
            self.assertEqual(session.request.call_count, 1)
            other_session.request.assert_not_called()

    def test_driver_group_pause_prevents_step_and_checkpoint(self):
        from wqb.research_group import stop_group
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = running_group(root)
            stop_group(Path(group['group_dir']), group['request_revision'])
            lane = root / 'lane-0'
            initial = dict(active=True, run_dir=str(lane), status='running')
            step = Mock(return_value={**initial, 'status': 'completed'})
            with patch('wqb.workflow_driver.schedule_run_checkpoint') as checkpoint:
                result = run_workflow_driver(SimpleNamespace(run_root=root), {}, step=step,
                                             status_reader=lambda: initial)
            step.assert_not_called()
            checkpoint.assert_not_called()
            self.assertEqual(result['runtime_status'], 'paused')

    def test_stop_during_local_step_prevents_followup_checkpoint(self):
        from wqb.research_group import stop_group
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = running_group(root)
            lane = root / 'lane-0'
            initial = dict(active=True, run_dir=str(lane), status='running')
            def step():
                """Input: none. Output: completed dict after concurrently persisted group Stop."""
                stop_group(Path(group['group_dir']), group['request_revision'])
                return {**initial, 'status': 'completed'}
            with patch('wqb.workflow_driver.schedule_run_checkpoint') as checkpoint:
                result = run_workflow_driver(SimpleNamespace(run_root=root), {}, step=step,
                                             status_reader=lambda: initial)
            checkpoint.assert_not_called()
            self.assertEqual(result['runtime_status'], 'paused')

    def test_429_driver_wait_does_not_schedule_model_or_spend_recovery_below_threshold(self):
        from wqb.rate_limit_state import RateLimitRecoveryRequired
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = running_group(root)
            lane = root / 'lane-0'
            source = root / 'research_groups/account_cooldown'
            now = datetime.now(timezone.utc)
            state = dict(status='cooldown', consecutive_429_count=1, attempt_count=1,
                         updated_at=now.isoformat(), retry_at=(now + timedelta(seconds=2)).isoformat())
            _write(source / 'rate_limit_state.json', state)
            initial = dict(active=True, run_dir=str(lane), status='running')
            steps = Mock(side_effect=[RateLimitRecoveryRequired(source, state),
                                     {**initial, 'status': 'completed'}])
            clock = [now]
            def sleep(seconds):
                """Input: float seconds. Output: None; advance offline clock."""
                clock[0] += timedelta(seconds=seconds)
            with patch('wqb.workflow_driver.schedule_run_checkpoint') as checkpoint:
                result = run_workflow_driver(SimpleNamespace(run_root=root), {}, step=steps,
                    status_reader=lambda: initial, now_func=lambda: clock[0].isoformat(), sleep_func=sleep)
            self.assertEqual(result['runtime_status'], 'completed')
            self.assertEqual(read_group(Path(group['group_dir']))['recoveries_used'], 0)
            self.assertEqual(checkpoint.call_count, 1)

    def test_driver_recovery_credits_are_shared_not_per_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = running_group(root, recoveries=1)
            now = datetime.now(timezone.utc).isoformat()
            for index in range(2):
                lane = root / f'lane-{index}'
                source = root / f'source-{index}'
                _write(source / 'rate_limit_state.json', dict(status='cooldown',
                    retry_at=now, updated_at=now, consecutive_429_count=3, attempt_count=3))
                initial = dict(active=True, run_dir=str(lane), status='running')
                steps = iter([{**initial, 'next_action': 'maintenance-blocker',
                    'source_bridge': dict(source_run_dir=str(source), metadata=dict(
                        retry_at=now, operator_acknowledgement_required=True))},
                    {**initial, 'status': 'completed'}])
                with patch('wqb.workflow_driver.schedule_run_checkpoint'):
                    result = run_workflow_driver(SimpleNamespace(run_root=root), {}, step=lambda: next(steps),
                        status_reader=lambda: initial, now_func=lambda: now, sleep_func=lambda seconds: None)
                self.assertEqual(result['runtime_status'], 'completed' if index == 0 else 'blocked')
                if index:
                    self.assertEqual(result['runtime_reason'], 'automatic_recovery_budget_exhausted')
            self.assertEqual(read_group(Path(group['group_dir']))['recoveries_used'], 1)

    def test_existing_post_guard_leases_local_and_shared_source_with_one_credit(self):
        from wqb.rate_limit_state import RateLimitRecoveryRequired, bounded_retry_is_authorized
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = running_group(root)
            lane = root / 'lane-0'
            source = root / 'source'
            shared = root / 'research_groups/account_cooldown'
            now = datetime.now(timezone.utc).isoformat()
            state = dict(status='cooldown', retry_at=now, updated_at=now,
                         attempt_count=2, consecutive_429_count=2)
            for directory in (source, shared):
                _write(directory / 'rate_limit_state.json', state)
            initial = dict(active=True, run_dir=str(lane), status='running')
            step = Mock(side_effect=[RateLimitRecoveryRequired(source, state),
                                     {**initial, 'status': 'completed'}])
            result = run_workflow_driver(SimpleNamespace(run_root=root), {}, step=step,
                status_reader=lambda: initial, now_func=lambda: now, sleep_func=lambda seconds: None)
            self.assertEqual(result['runtime_status'], 'completed')
            for directory in (source, shared):
                self.assertTrue(bounded_retry_is_authorized(json.loads(
                    (directory / 'rate_limit_state.json').read_text()), now), directory)
            self.assertEqual(read_group(Path(group['group_dir']))['recoveries_used'], 1)


if __name__ == '__main__':
    unittest.main()
