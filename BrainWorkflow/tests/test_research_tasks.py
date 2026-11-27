"""Independent Start identities and task-local authority, using isolated storage only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class ResearchTasksTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'runs'
        self.selection = dict(selected_option_id='option-3', scope=dict(region='ALL', universe='LARGE', delay=1))

    def test_same_scope_distinct_commands_and_same_command_idempotency(self):
        from wqb.research_tasks import create_task, list_tasks
        first = create_task(self.root, 'one', self.selection)
        second = create_task(self.root, 'two', self.selection)
        self.assertNotEqual(first['task_id'], second['task_id'])
        self.assertRegex(first['task_id'], r'^ALL_LARGE_D1_\d{8}T\d{6}_[a-f0-9]{8}$')
        self.assertEqual(create_task(self.root, 'one', self.selection), first)
        self.assertEqual(len(list_tasks(self.root)), 2)
        with self.assertRaisesRegex(ValueError, 'command'):
            create_task(self.root, 'one', dict(self.selection, scope=dict(region='USA')))

    def test_concurrent_commands_do_not_overwrite(self):
        from wqb.research_tasks import create_task, list_tasks
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _: create_task(self.root, 'same', self.selection), range(4)))
        self.assertEqual(len({row['task_id'] for row in rows}), 1)
        self.assertEqual(len(list_tasks(self.root)), 1)

    def test_task_failure_does_not_affect_other_or_reopen(self):
        from wqb.research_tasks import create_task, update_task, read_task
        first = create_task(self.root, 'one', self.selection)
        second = create_task(self.root, 'two', self.selection)
        update_task(self.root, first['task_id'], status='failed', reason='signature unknown')
        self.assertEqual(read_task(self.root, second['task_id'])['status'], 'accepted')
        with self.assertRaisesRegex(ValueError, 'terminal'):
            update_task(self.root, first['task_id'], status='running')

    def test_unknown_scope_does_not_prevent_task_creation(self):
        from wqb.research_tasks import create_task
        row = create_task(self.root, 'activity', dict(selected_option_id='new-competition', scope={}))
        self.assertTrue(row['task_id'].startswith('UNKNOWN_UNKNOWN_DUNKNOWN_'))

    def test_task_runtime_uses_same_workspace_budget(self):
        from wqb.research_tasks import create_task, task_runs_root, canonical_runs_root
        from wqb.daily_simulation_budget import ensure_daily_policy
        task = create_task(self.root, 'one', self.selection)
        runtime = task_runs_root(self.root, task['task_id'])
        self.assertEqual(canonical_runs_root(runtime), self.root.absolute())
        self.assertEqual(ensure_daily_policy(runtime), ensure_daily_policy(self.root))
        self.assertFalse((runtime / 'daily_simulation_budget').exists())

    def test_unsafe_task_lookup_is_refused(self):
        from wqb.research_tasks import read_task
        with self.assertRaises(ValueError):
            read_task(self.root, '../escape')

    def test_identity_reservations_are_shared_between_tasks(self):
        from wqb.research_tasks import create_task, task_runs_root
        from wqb.research_group import create_group, reserve_identity
        groups = []
        for command in ('one', 'two'):
            row = create_task(self.root, command, self.selection)
            group = create_group(task_runs_root(self.root, row['task_id']),
                [dict(run_id='lane', plan_digest='a' * 64)],
                dict(enable_live_api=False, max_runtime_seconds=3600, max_recoveries=3))
            groups.append(Path(group['group_dir']))
        self.assertTrue(reserve_identity(groups[0], 'lane', 'b' * 64))
        self.assertFalse(reserve_identity(groups[1], 'lane', 'b' * 64))

    def test_task_sees_preserved_workspace_simulation_history(self):
        import json
        import hashlib
        from wqb.research_tasks import create_task, task_runs_root
        from wqb.cli import run_root_expression_hashes
        task = create_task(self.root, 'one', self.selection)
        values = ['d' * 64]
        (self.root / 'simulation_identity_history.json').write_text(json.dumps(dict(schema_version=1,
            identities=values, identities_sha256=hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest())), encoding='utf-8')
        self.assertIn(values[0], run_root_expression_hashes(task_runs_root(self.root, task['task_id'])))

    def test_corrupt_task_cannot_block_distinct_command_or_replay_original(self):
        from wqb.research_tasks import create_task, task_runs_root, list_tasks
        first = create_task(self.root, 'one', self.selection)
        (task_runs_root(self.root, first['task_id']).parent / 'task.json').write_text('{broken', encoding='utf-8')
        second = create_task(self.root, 'two', self.selection)
        self.assertNotEqual(second['task_id'], first['task_id'])
        self.assertEqual(len(list_tasks(self.root)), 2)
        with self.assertRaises(ValueError):
            create_task(self.root, 'one', self.selection)

    def test_terminal_task_blocks_late_group_submission(self):
        from wqb.research_tasks import create_task, task_runs_root, update_task
        from wqb.research_group import create_group, require_group_running
        from wqb.runtime_control import RuntimePaused
        task = create_task(self.root, 'one', self.selection)
        runtime = task_runs_root(self.root, task['task_id'])
        create_group(runtime, [dict(run_id='lane', plan_digest='a' * 64)],
            dict(enable_live_api=False, max_runtime_seconds=3600, max_recoveries=3))
        update_task(self.root, task['task_id'], status='failed', reason='terminal fault')
        with self.assertRaisesRegex(RuntimePaused, 'task ended'):
            require_group_running(runtime / 'lane')
