from pathlib import Path
import tempfile
import unittest


class RuntimeHeartbeatTests(unittest.TestCase):
    def test_heartbeat_does_not_mutate_pause_intent(self):
        from wqb.runtime_control import start_runtime_heartbeat, request_runtime_state, read_runtime_control
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            request_runtime_state(run, 'paused')
            before = (run / 'runtime_control.json').read_bytes()
            stop, worker = start_runtime_heartbeat(run, interval_seconds=.01)
            try:
                worker.join(.06)
                control = read_runtime_control(run)
                self.assertTrue(control.get('heartbeat_at'))
                self.assertEqual(control['desired_state'], 'paused')
                self.assertEqual((run / 'runtime_control.json').read_bytes(), before)
            finally:
                stop.set()
                worker.join(1)
            self.assertFalse(worker.is_alive())
