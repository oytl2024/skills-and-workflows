"""N-way local coordination never creates independent account budgets."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wqb.research_group import create_group, read_group, stop_group, next_lane, reserve_identity


def plans(count):
    """Input: positive lane count int. Output: unique offline lane plans list[dict]."""
    return [dict(run_id=f'lane-{i}', plan_digest=str(i) * 64) for i in range(count)]


class ResearchGroupTests(unittest.TestCase):
    def test_paused_group_blocks_existing_submission_boundary(self):
        from wqb.runtime_control import CONTROL_ENV, RuntimePaused, check_submission_allowed
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_group(root, plans(1), self.authority())
            with patch.dict('os.environ', {CONTROL_ENV: str(root / 'lane-0')}):
                with self.assertRaisesRegex(RuntimePaused, 'group is paused'):
                    check_submission_allowed()

    def test_running_group_dispatch_is_fair_and_stop_wins(self):
        from wqb.research_group import resume_group
        with tempfile.TemporaryDirectory() as tmp:
            group = create_group(Path(tmp), plans(4), self.authority())
            path = Path(group['group_dir'])
            with patch('wqb.runtime_control.has_runtime_authority', return_value=True):
                current = resume_group(path, group['request_revision'])
            self.assertEqual([next_lane(path, [f'lane-{i}' for i in range(4)]) for _ in range(8)],
                             [f'lane-{i}' for i in range(4)] * 2)
            stop_group(path, current['request_revision'])
            self.assertIsNone(next_lane(path, ['lane-0']))

    def authority(self):
        """Input: test instance. Output: finite authority dict, without live permission."""
        return dict(enable_live_api=False, max_runtime_seconds=3600, max_recoveries=3)

    def test_n_way_membership_is_generic_and_budget_is_not_multiplied(self):
        for count in (1, 2, 4):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as tmp:
                group = create_group(Path(tmp), plans(count), self.authority())
                loaded = read_group(Path(group['group_dir']))
                self.assertEqual(len(loaded['lanes']), count)
                self.assertEqual(loaded['desired_state'], 'paused')
                self.assertNotIn('daily_limit', loaded['authority'])
                self.assertEqual(loaded['authority']['max_runtime_seconds'], 3600)

    def test_invalid_membership_cannot_adopt_old_run_or_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for items in ([], [dict(run_id='../outside', plan_digest='a' * 64)], plans(2) * 2):
                with self.subTest(items=items), self.assertRaises(ValueError):
                    create_group(root, items, self.authority())
            (root / 'lane-0').mkdir()
            with self.assertRaises(ValueError):
                create_group(root, plans(1), self.authority())

    def test_fair_round_robin_and_group_stop_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            group = create_group(Path(tmp), plans(4), self.authority())
            path = Path(group['group_dir'])
            # A fresh group is paused; read-only navigation must not dispatch.
            self.assertIsNone(next_lane(path, ready=['lane-0']))
            stopped = stop_group(path, group['request_revision'])
            self.assertEqual(stopped['desired_state'], 'paused')
            with self.assertRaises(ValueError):
                stop_group(path, group['request_revision'])

    def test_global_identity_reservation_is_idempotent_for_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            group = create_group(Path(tmp), plans(2), self.authority())
            path = Path(group['group_dir'])
            self.assertTrue(reserve_identity(path, 'lane-0', 'a' * 64))
            self.assertTrue(reserve_identity(path, 'lane-0', 'a' * 64))
            self.assertFalse(reserve_identity(path, 'lane-1', 'a' * 64))
            with self.assertRaises(ValueError):
                reserve_identity(path, 'foreign', 'b' * 64)

    def test_manifest_tampering_is_not_a_new_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            group = create_group(Path(tmp), plans(2), self.authority())
            path = Path(group['group_dir'])
            manifest = path / 'group_manifest.json'
            row = json.loads(manifest.read_text())
            row['lanes'][0]['run_id'] = 'foreign'
            manifest.write_text(json.dumps(row))
            with self.assertRaises(ValueError):
                read_group(path)

    def test_copied_member_binding_does_not_adopt_foreign_run(self):
        from wqb.research_group import group_for_run
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_group(root, plans(1), self.authority())
            foreign = root / 'foreign'
            foreign.mkdir()
            (foreign / 'research_group_binding.json').write_bytes(
                (root / 'lane-0/research_group_binding.json').read_bytes())
            with self.assertRaisesRegex(ValueError, 'member|identity'):
                group_for_run(foreign)


if __name__ == '__main__':
    unittest.main()
