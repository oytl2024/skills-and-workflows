"""Maintenance probe cannot become another simulation writer or credential store."""
from types import SimpleNamespace
import unittest


class CnhkProbeTests(unittest.TestCase):
    def test_only_documented_read_routes_are_forwarded(self):
        from scripts.probe_cnhkmcp import ReadOnlySession
        calls = []
        client = SimpleNamespace(request=lambda method, path, **kw: calls.append((method, path)) or 'response')
        session = ReadOnlySession(client, max_reads=2)
        self.assertEqual(session.get('https://api.worldquantbrain.com/operators'), 'response')
        self.assertEqual(session.options('https://api.worldquantbrain.com/simulations'), 'response')
        with self.assertRaisesRegex(ValueError, 'budget'):
            session.get('https://api.worldquantbrain.com/tutorials')
        self.assertEqual(len(calls), 2)

    def test_external_mutation_and_credential_routes_never_forward(self):
        from scripts.probe_cnhkmcp import ReadOnlySession
        calls = []
        session = ReadOnlySession(SimpleNamespace(request=lambda *a, **kw: calls.append(a)))
        for url in ('https://example.com/operators', 'http://api.worldquantbrain.com/operators',
                    'https://api.worldquantbrain.com/alphas/x',
                    'https://api.worldquantbrain.com/tutorial-pages/../authentication',
                    'https://api.worldquantbrain.com/operators?token=secret',
                    'https://user:pass@api.worldquantbrain.com/operators'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                session.get(url)
        self.assertFalse(hasattr(session, 'post'))
        self.assertEqual(calls, [])

    def test_upstream_artifact_hash_is_required_before_execution(self):
        import tempfile
        from pathlib import Path
        from scripts.probe_cnhkmcp import load_upstream
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / 'untrusted.whl'
            wheel.write_bytes(b'not a wheel')
            with self.assertRaisesRegex(ValueError, 'hash'):
                load_upstream(wheel, Path(directory) / 'source')
