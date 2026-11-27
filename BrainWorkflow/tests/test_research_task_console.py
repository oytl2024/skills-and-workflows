"""Task acceptance never depends on an unrelated global failed Start."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wqb.console_state import ConsolePaths


class ResearchTaskConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.paths = ConsolePaths(root, root / 'product', root / 'knowledge', root / 'runs',
            root / 'milestone.md', root / 'todo.md', root / 'runs/console_jobs')
        self.command = dict(action='start', command_id='one', selected_option_id='option-3',
            selected_scope=dict(region='ALL', universe='LARGE', delay=1))

    def test_snapshot_keeps_new_options_clickable_despite_old_global_blocker(self):
        from wqb.console_api import project_application
        import json
        config = self.paths.workflow_root / 'configs'
        config.mkdir(parents=True)
        (config / 'workflow_local.json').write_text(json.dumps(dict(independent_tasks_version=1)), encoding='utf-8')
        state = dict(option_cards=[dict(option_id='new-event', title='New competition', primary_incentive='competition')],
            current_work=dict(blocker='old unknown task'), active_workflow=dict(exists=True, run_id='old'))
        result = project_application(self.paths, state, 'test', 1)
        self.assertEqual(result.get('task_mode'), 1)
        self.assertTrue(result['allowed_actions']['start'])
        self.assertTrue(result['options'][0]['startable'])
        self.assertEqual(result['tasks'], [])

    def test_starts_route_into_distinct_namespaces(self):
        from wqb.research_task_console import start_task
        from wqb.research_tasks import list_tasks
        calls = []
        def dispatch(paths, form, action):
            calls.append(paths.runs_root)
            return SimpleNamespace(job_id='job-' + str(len(calls)), status='running')
        with patch('wqb.console_start.application_start_form', return_value=dict(selected_region='ALL', selected_universe='LARGE', selected_delay=1)), \
                patch('wqb.console_server._run_console_action_unlocked', side_effect=dispatch):
            first = start_task(self.paths, self.command)
            second = start_task(self.paths, dict(self.command, command_id='two'))
        self.assertEqual(first['status'], 'accepted')
        self.assertNotEqual(calls[0], calls[1])
        self.assertNotEqual(first['task_id'], second['task_id'])
        self.assertEqual(len(list_tasks(self.paths.runs_root)), 2)

    def test_unresolvable_preparation_is_terminal_report_not_notification(self):
        from wqb.research_task_console import start_task
        from wqb.research_tasks import list_tasks
        with patch('wqb.console_start.application_start_form', side_effect=ValueError('Unknown activity parameters')), \
                patch('wqb.preflight_notifications.notify_preflight_blocker') as notice:
            result = start_task(self.paths, self.command)
        notice.assert_not_called()
        self.assertEqual(result['status'], 'accepted')
        row = list_tasks(self.paths.runs_root)[0]
        self.assertEqual(row['status'], 'failed')
        self.assertTrue(Path(row['report_path']).exists())

    def test_stop_only_selected_task(self):
        from wqb.research_tasks import create_task, read_task
        from wqb.research_task_console import stop_task
        first = create_task(self.paths.runs_root, 'one', dict(scope={}))
        second = create_task(self.paths.runs_root, 'two', dict(scope={}))
        stop_task(self.paths, first['task_id'])
        self.assertEqual(read_task(self.paths.runs_root, first['task_id'])['status'], 'stopped')
        self.assertEqual(read_task(self.paths.runs_root, second['task_id'])['status'], 'accepted')

    def test_failed_preparation_is_reconciled_after_lost_callback(self):
        import json
        from wqb.research_tasks import create_task, update_task
        from wqb.research_task_console import refresh_task
        task = create_task(self.paths.runs_root, 'lost', dict(scope={}))
        update_task(self.paths.runs_root, task['task_id'], status='preparing', job_id='job-one')
        directory = self.paths.job_root / 'job-one'
        directory.mkdir(parents=True)
        (directory / 'job.json').write_text(json.dumps(dict(status='failed', error='Unknown parameter', job_id='job-one')), encoding='utf-8')
        row = refresh_task(self.paths, task['task_id'])
        self.assertEqual(row['status'], 'failed')
        self.assertTrue(Path(row['report_path']).exists())

    def test_failed_lane_owner_ends_task_even_if_runtime_status_never_changed(self):
        import json
        from wqb.research_tasks import create_task, update_task, task_runs_root
        from wqb.research_task_console import refresh_task
        from wqb.research_group import create_group
        task = create_task(self.paths.runs_root, 'owner-fault', dict(scope={}))
        runtime = task_runs_root(self.paths.runs_root, task['task_id'])
        group = create_group(runtime, [dict(run_id='lane', plan_digest='a' * 64)],
            dict(enable_live_api=False, max_runtime_seconds=3600, max_recoveries=3))
        update_task(self.paths.runs_root, task['task_id'], status='running', group_dir=group['group_dir'])
        (runtime / 'lane/runtime').mkdir()
        (runtime / 'lane/runtime_status.json').write_text(json.dumps(dict(status='paused')), encoding='utf-8')
        (runtime / 'lane/runtime/group_worker.json').write_text(json.dumps(dict(status='failed')), encoding='utf-8')
        ended = refresh_task(self.paths, task['task_id'])
        self.assertEqual(ended['status'], 'failed')
        self.assertTrue(Path(ended['report_path']).exists())
