"""One report per ended task, retaining observations instead of duplicate knowledge exports."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class ResearchTaskReportTests(unittest.TestCase):
    def test_summary_reads_report_without_duplicate_ledger_or_raw_export(self):
        from wqb.research_tasks import create_task, task_runs_root, update_task
        from wqb.research_task_report import publish_report
        from wqb.research_record import empty_research_record, sync_research_record_to_machine, sync_research_record_to_raw, load_research_record_ledger
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = create_task(root / 'runs', 'one', dict(scope={}))
            run = task_runs_root(root / 'runs', task['task_id']) / 'lane'
            run.mkdir()
            planning = run / 'runtime/retrieval_research_planning'
            planning.mkdir(parents=True)
            (planning / 'task.json').write_text(json.dumps(dict(identity=dict(private_context='omit this'),
                answer=dict(summary='Economic hypothesis retained', designs=[], tree=dict(roots=[])))), encoding='utf-8')
            record = empty_research_record('lane', 'test research')
            sync_research_record_to_machine(record, root / 'knowledge', run_dir=run)
            sync_research_record_to_raw(record, root / 'knowledge/raw', run_dir=run)
            self.assertFalse((root / 'knowledge/machine/research_records.jsonl').exists())
            self.assertFalse((root / 'knowledge/raw/research').exists())
            update_task(root / 'runs', task['task_id'], status='failed', reason='Unknown signature')
            path = publish_report(root / 'runs', task['task_id'], root / 'knowledge')
            self.assertEqual(path.parent, root / 'knowledge/researchreport')
            body = path.read_text(encoding='utf-8')
            self.assertIn('Economic hypothesis retained', body)
            self.assertNotIn('omit this', body)
            rows = load_research_record_ledger(root / 'knowledge')
            self.assertEqual([row['run_id'] for row in rows], [task['task_id']])
            self.assertEqual(rows[0]['final_state'], 'failed')

    def test_legacy_report_remains_readable_without_duplicate_publication(self):
        from wqb.research_tasks import create_task, update_task
        from wqb.research_task_report import publish_report, load_report_records
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            knowledge = root / 'knowledge'
            task = create_task(root / 'runs', 'one', dict(scope={}))
            update_task(root / 'runs', task['task_id'], status='failed', reason='Ended')
            path = publish_report(root / 'runs', task['task_id'], knowledge)
            legacy = knowledge / 'machine/researchreport' / path.name
            legacy.parent.mkdir(parents=True)
            path.replace(legacy)
            update_task(root / 'runs', task['task_id'], report_path=str(legacy))
            self.assertEqual(publish_report(root / 'runs', task['task_id'], knowledge), legacy)
            self.assertEqual(len(load_report_records(knowledge)), 1)
            self.assertFalse(path.exists())

    def test_terminal_report_contains_every_point_and_error_once(self):
        from wqb.research_tasks import create_task, task_runs_root, update_task
        from wqb.research_task_report import publish_report
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = create_task(root / 'runs', 'one', dict(scope=dict(region='ALL', universe='LARGE', delay=1)))
            run = task_runs_root(root / 'runs', task['task_id']) / 'lane'
            run.mkdir()
            points = [dict(expression=f'rank(x{i})', alpha_id=str(i), settings=dict(decay=i), metrics=dict(sharpe=i)) for i in range(40)]
            (run / 'all_alphas.jsonl').write_text('\n'.join(json.dumps(row) for row in points), encoding='utf-8')
            (run / 'run_errors.jsonl').write_text(json.dumps(dict(code='unknown_signature', message='No verified signature', password='sensitive')), encoding='utf-8')
            update_task(root / 'runs', task['task_id'], status='failed', reason='unknown parameter')
            path = publish_report(root / 'runs', task['task_id'], root / 'knowledge')
            body = path.read_text(encoding='utf-8')
            self.assertEqual(body.count('### Point '), 40)
            self.assertIn('rank(x39)', body)
            self.assertIn('unknown_signature', body)
            self.assertNotIn('sensitive', body)
            self.assertEqual(path, publish_report(root / 'runs', task['task_id'], root / 'knowledge'))
            self.assertEqual(body, path.read_text(encoding='utf-8'))
            self.assertEqual(len(list((root / 'knowledge').rglob('*.*'))), 1)

    def test_early_failure_report_and_active_task_protection(self):
        from wqb.research_tasks import create_task, update_task
        from wqb.research_task_report import publish_report
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = create_task(root / 'runs', 'one', dict(scope={}))
            with self.assertRaisesRegex(ValueError, 'terminal'):
                publish_report(root / 'runs', task['task_id'], root / 'knowledge')
            update_task(root / 'runs', task['task_id'], status='failed', reason='Preparation failed before any experiment')
            path = publish_report(root / 'runs', task['task_id'], root / 'knowledge')
            self.assertIn('Preparation failed', path.read_text(encoding='utf-8'))
            self.assertIn('No measured experiment', path.read_text(encoding='utf-8'))
