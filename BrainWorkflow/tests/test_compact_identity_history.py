"""Minimal dedup history survives removal of old run directories."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest


class CompactIdentityHistoryTests(unittest.TestCase):
    def test_compact_history_and_current_events_are_both_seen(self):
        from wqb.cli import run_root_expression_hashes
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identities = ['a' * 64, 'b' * 64]
            digest = hashlib.sha256(json.dumps(identities, separators=(',', ':')).encode()).hexdigest()
            (root / 'simulation_identity_history.json').write_text(json.dumps(dict(
                schema_version=1, identities=identities, identities_sha256=digest)), encoding='utf-8')
            run = root / 'new-run'
            run.mkdir()
            (run / 'simulation_events.jsonl').write_text(json.dumps(dict(
                event='SUBMITTED', expression_hash='c' * 64)) + '\n', encoding='utf-8')
            self.assertEqual(run_root_expression_hashes(root), set(identities + ['c' * 64]))
            (run / 'simulation_events.jsonl').unlink()
            run.rmdir()
            self.assertEqual(run_root_expression_hashes(root), set(identities))

    def test_corrupt_compact_history_cannot_silently_reset_dedup(self):
        from wqb.cli import run_root_expression_hashes
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'simulation_identity_history.json').write_text(json.dumps(dict(
                schema_version=1, identities=['a' * 64], identities_sha256='wrong')), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'identity history'):
                run_root_expression_hashes(root)
