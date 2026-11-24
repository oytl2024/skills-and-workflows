"""Current-only maintenance must not accumulate whole-vault jobs or reports."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class CurrentKnowledgeStorageTests(unittest.TestCase):
    def test_current_report_replaces_previous_summary_without_raw_history(self):
        from wqb.knowledge_maintenance import _write_report
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'machine').mkdir()
            (root / 'machine/knowledge_storage_policy.json').write_text(
                json.dumps(dict(schema_version=1, mode='current_only_v1')), encoding='utf-8')
            for count in (1, 2):
                report = dict(generated_at='2026-11-24T14:00:00+00:00', status='completed',
                    data_compile=dict(updated_fields=count), large_detail=['x' * 1000] * 100)
                path = _write_report(root, report)
            self.assertEqual(path, root / 'machine/maintenance_summary.json')
            self.assertLess(path.stat().st_size, 10000)
            self.assertEqual(json.loads(path.read_text())['data_compile']['updated_fields'], 2)
            self.assertFalse((root / 'raw/maintenance/compile_reports').exists())

    def test_current_mode_never_prepares_whole_vault_semantic_inventory(self):
        from wqb.full_semantic_compile import prepare_full_semantic_compile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'machine').mkdir()
            (root / 'machine/knowledge_storage_policy.json').write_text(
                json.dumps(dict(schema_version=1, mode='current_only_v1')), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'current-only'):
                prepare_full_semantic_compile(root, {})
            self.assertFalse((root / 'machine/semantic_inventories').exists())
            self.assertFalse((root / 'machine/semantic_jobs').exists())

    def test_current_maintenance_does_not_migrate_or_restore_old_jobs(self):
        from wqb import knowledge_maintenance as maintenance
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'machine').mkdir()
            (root / 'machine/knowledge_storage_policy.json').write_text(
                json.dumps(dict(schema_version=1, mode='current_only_v1')), encoding='utf-8')
            with patch.object(maintenance, '_compile_current_fields', return_value=dict(status='unchanged')), \
                    patch.object(maintenance, 'compile_human_experience_wiki', return_value=dict(status='completed')), \
                    patch.object(maintenance, 'compile_interaction_lessons', return_value=dict(status='completed')), \
                    patch.object(maintenance, 'run_knowledge_vault_migration', side_effect=AssertionError('old migration')):
                result = maintenance.run_knowledge_maintenance(root)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['mode'], 'current_only_v1')
            self.assertFalse((root / 'machine/semantic_inventories').exists())
