"""Offline actual POST admission, crash leases and durable Resume receipts."""

import json
from contextlib import ExitStack
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time
import traceback
import unittest
from unittest.mock import patch

from tests.test_group_runtime_integration import running_group, transport
from wqb.lockfile import json_lock_transition_guard
from wqb.research_group import _guard, create_group, read_group, resume_group, stop_group, group_submission_gate
from wqb.runtime_control import CONTROL_ENV, RuntimePaused, read_runtime_control, request_runtime_state
from wqb.simulator import submit_simulation


def post_lane(root, index, results, rounds=6):
    """Input: root str/index int/IPC/rounds int. Output: fake POST log and IPC outcome; no network."""
    root = Path(root)
    os.environ[CONTROL_ENV] = str(root / f'lane-{index}')
    client, session = transport()
    response = session.request.return_value

    def dispatch(*args, **kwargs):
        """Input: transport arguments. Output: fake response, logging actual fenced POST order."""
        with (root / 'posts.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(index) + '\n')
        time.sleep(.025)
        return response

    session.request.side_effect = dispatch
    try:
        for number in range(rounds):
            submit_simulation(client, dict(regular=f'rank(close)+{index * 100 + number}', settings={}))
        results.put((index, 'sent'))
    except Exception as error:
        results.put((index, type(error).__name__, str(error), traceback.format_exc()))


class GroupDispatchFairnessTests(unittest.TestCase):
    def test_slow_healthy_n4_queue_outlives_lock_acquisition_deadline(self):
        """Input: none. Output: None; scaled slow requests must not terminate queued healthy lanes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = running_group(root, 4)
            path = Path(group['group_dir'])
            admitted, errors = [], []
            def enter(index):
                """Input: lane index int. Output: None; hold the actual admission fence without network."""
                try:
                    with group_submission_gate(root / f'lane-{index}', fair=True):
                        admitted.append(index)
                        time.sleep(.15)
                except Exception as error:
                    errors.append((index, str(error)))
            workers = [threading.Thread(target=enter, args=(index,)) for index in range(4)]
            with patch('wqb.research_group.SUBMISSION_WAIT_SECONDS', .2):
                try:
                    with json_lock_transition_guard(path / 'submission_fence', 1, .01, 'fixture busy'):
                        for worker in workers:
                            worker.start()
                        self.wait_ready(path, 4)
                    for worker in workers:
                        worker.join(5)
                    self.assertFalse(any(worker.is_alive() for worker in workers))
                    self.assertEqual(errors, [])
                    self.assertEqual(admitted, [0, 1, 2, 3])
                finally:
                    for worker in workers:
                        worker.join(5)

    def wait_ready(self, group, count):
        """Input: group Path/count int. Output: None; require persistent admission registrations."""
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if len(read_group(group).get('waiting_submissions', {})) == count:
                return
            time.sleep(.01)
        self.fail(f'{count} POST waiters never registered: {read_group(group).get("waiting_submissions")}')

    def test_actual_multiprocess_post_round_robin_n1_n2_n4(self):
        ctx = multiprocessing.get_context('spawn')
        for count in (1, 2, 4):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                group = running_group(root, count)
                path = Path(group['group_dir'])
                results = ctx.Queue()
                workers = [ctx.Process(target=post_lane, args=(tmp, i, results)) for i in range(count)]
                started = time.monotonic()
                try:
                    with json_lock_transition_guard(path / 'submission_fence', 1, .01, 'fixture busy'):
                        for worker in workers:
                            worker.start()
                        try:
                            self.wait_ready(path, count)
                        except AssertionError:
                            observed = []
                            while not results.empty():
                                observed.append(results.get(timeout=1))
                            self.fail(f'waiting registration failed: {observed}; {read_group(path)}')
                    rows = [results.get(timeout=30) for _ in workers]
                    for worker in workers:
                        worker.join(5)
                        self.assertEqual(worker.exitcode, 0)
                    self.assertTrue(all(row[1] == 'sent' for row in rows), rows)
                    posts = [json.loads(line) for line in (root / 'posts.jsonl').read_text().splitlines()]
                    self.assertEqual(posts, list(range(count)) * 6)
                    self.assertEqual(sum(read_runtime_control(root / f'lane-{i}').get(
                        'simulation_attempts', 0) for i in range(count)), len(posts))
                    self.assertEqual(read_group(path)['recoveries_used'], 0)
                    self.assertEqual(read_group(path)['authority'], group['authority'])
                    self.assertFalse(read_group(path).get('waiting_submissions'))
                    print(f'fair POST N={count}: {len(posts)} requests in {time.monotonic() - started:.3f}s')
                finally:
                    for worker in workers:
                        if worker.is_alive():
                            worker.terminate()
                        if worker.pid:
                            worker.join(5)
                    results.close()

    def test_resume_preallocated_revision_is_durable_and_stop_invalidates_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            group = running_group(Path(tmp), 1)
            path = Path(group['group_dir'])
            stopped = stop_group(path, group['request_revision'])
            planned = 'a' * 32
            receipt = resume_group(path, stopped['request_revision'], request_revision=planned)
            self.assertEqual(receipt['request_revision'], planned)
            self.assertEqual(read_group(path)['request_revision'], planned)
            self.assertEqual(receipt['authority'], group['authority'])
            newer = stop_group(path, planned)
            self.assertNotEqual(newer['request_revision'], planned)
            with self.assertRaisesRegex(ValueError, 'stale'):
                resume_group(path, stopped['request_revision'], request_revision=planned)

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_group_write_waits_for_brief_windows_reader_without_losing_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            group = running_group(Path(tmp), 1)
            path = Path(group['group_dir'])
            reader = (path / 'group_intent.json').open('rb')
            release = threading.Timer(.1, reader.close)
            release.start()
            try:
                result = resume_group(path, group['request_revision'], request_revision='f' * 32)
                self.assertEqual(result['request_revision'], 'f' * 32)
            finally:
                release.join(5)
                reader.close()

    def test_resume_rejects_invalid_or_current_preallocated_revision_without_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            group = running_group(Path(tmp), 1)
            path = Path(group['group_dir'])
            before = (path / 'group_intent.json').read_bytes()
            for revision in ('', 'A' * 32, 'a' * 31, 'a' * 33, 42, group['request_revision']):
                with self.subTest(revision=revision), self.assertRaises(ValueError):
                    resume_group(path, group['request_revision'], request_revision=revision)
                self.assertEqual((path / 'group_intent.json').read_bytes(), before)

    def test_direct_gate_enforces_stop_and_live_authority(self):
        for live in (False, True):
            with self.subTest(live=live), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                group = running_group(root, 1, live=live)
                if live:
                    stop_group(Path(group['group_dir']), group['request_revision'])
                with self.assertRaises(RuntimePaused):
                    with group_submission_gate(root / 'lane-0', fair=True):
                        self.fail('unauthorized POST admitted')

    def test_control_pause_acknowledgement_does_not_require_post_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = create_group(root, [dict(run_id='lane-0', plan_digest='0' * 64)],
                                 dict(enable_live_api=False, max_runtime_seconds=3600, max_recoveries=1))
            result = request_runtime_state(root / 'lane-0', 'paused', enable_live_api=False)
            self.assertEqual(result['desired_state'], 'paused')
            self.assertEqual(read_group(Path(group['group_dir']))['cursor'], 0)
            self.assertFalse(read_group(Path(group['group_dir'])).get('waiting_submissions'))

    def test_admission_never_holds_fence_while_waiting_for_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = running_group(root, 1)
            path = Path(group['group_dir'])
            errors = []

            def enter():
                """Input: none. Output: None; attempt fair admission on an independent OS lock handle."""
                try:
                    with group_submission_gate(root / 'lane-0', fair=True):
                        pass
                except Exception as error:
                    errors.append(error)

            worker = threading.Thread(target=enter)
            try:
                with ExitStack() as fence:
                    fence.enter_context(json_lock_transition_guard(path / 'submission_fence', 1, .01, 'fixture busy'))
                    worker.start()
                    self.wait_ready(path, 1)
                    with _guard(path):
                        fence.close()
                        time.sleep(.15)
                        with json_lock_transition_guard(path / 'submission_fence', .5, .005, 'admission lock inversion'):
                            pass
            finally:
                worker.join(6)
            self.assertFalse(worker.is_alive())
            self.assertFalse(errors)

    def test_dead_waiter_lease_is_pruned_without_attempt_or_recovery(self):
        ctx = multiprocessing.get_context('spawn')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = running_group(root, 2)
            path = Path(group['group_dir'])
            results = ctx.Queue()
            dead = ctx.Process(target=post_lane, args=(tmp, 0, results, 1))
            live = ctx.Process(target=post_lane, args=(tmp, 1, results, 1))
            try:
                with json_lock_transition_guard(path / 'submission_fence', 1, .01, 'fixture busy'):
                    dead.start()
                    self.wait_ready(path, 1)
                    dead.terminate()
                    dead.join(5)
                    self.assertIsNotNone(dead.exitcode)
                    live.start()
                    self.wait_ready(path, 1)
                    deadline = time.monotonic() + 10
                    while 'lane-0' in read_group(path).get('waiting_submissions', {}) and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertEqual(set(read_group(path)['waiting_submissions']), {'lane-1'})
                self.assertEqual(results.get(timeout=20), (1, 'sent'))
                live.join(5)
                self.assertEqual(live.exitcode, 0)
                self.assertEqual((root / 'posts.jsonl').read_text().splitlines(), ['1'])
                self.assertEqual(read_runtime_control(root / 'lane-0').get('simulation_attempts', 0), 0)
                self.assertEqual(read_runtime_control(root / 'lane-1')['simulation_attempts'], 1)
                self.assertEqual(read_group(path)['recoveries_used'], 0)
            finally:
                for worker in (dead, live):
                    if worker.is_alive():
                        worker.terminate()
                    if worker.pid:
                        worker.join(5)
                results.close()

    def test_stop_then_resume_rejects_old_waiter_and_new_client_can_progress(self):
        ctx = multiprocessing.get_context('spawn')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = running_group(root, 1)
            path = Path(group['group_dir'])
            results = ctx.Queue()
            worker = ctx.Process(target=post_lane, args=(tmp, 0, results, 1))
            errors = []

            def stop():
                """Input: none. Output: None; persist Stop while parent holds test fence."""
                try:
                    stop_group(path, group['request_revision'])
                except Exception as error:
                    errors.append(error)

            stopper = threading.Thread(target=stop)
            try:
                with json_lock_transition_guard(path / 'submission_fence', 1, .01, 'fixture busy'):
                    worker.start()
                    self.wait_ready(path, 1)
                    stopper.start()
                    deadline = time.monotonic() + 5
                    while read_group(path)['desired_state'] != 'paused' and time.monotonic() < deadline:
                        time.sleep(.01)
                    paused = read_group(path)
                    self.assertEqual(paused['desired_state'], 'paused')
                    resume_group(path, paused['request_revision'])
                result = results.get(timeout=20)
                self.assertEqual(result[1], 'RuntimePaused', result)
                worker.join(5)
                stopper.join(5)
                self.assertFalse(stopper.is_alive())
                self.assertFalse(errors)
                self.assertFalse((root / 'posts.jsonl').exists())
                self.assertEqual(read_runtime_control(root / 'lane-0').get('simulation_attempts', 0), 0)
                self.assertFalse(read_group(path).get('waiting_submissions'))
                client, session = transport()
                with patch.dict(os.environ, {CONTROL_ENV: str(root / 'lane-0')}):
                    submit_simulation(client, dict(regular='rank(close)', settings={}))
                self.assertEqual(session.request.call_count, 1)
            finally:
                if worker.is_alive():
                    worker.terminate()
                if worker.pid:
                    worker.join(5)
                if stopper.ident:
                    stopper.join(5)
                results.close()
