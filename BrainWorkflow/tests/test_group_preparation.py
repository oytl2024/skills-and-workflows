"""New-lane preparation certifies raw before model planning and never starts workers."""

from types import SimpleNamespace
import unittest

from wqb.benchmark_rules import benchmark_rules_path_for_knowledge, default_benchmark_rules, write_benchmark_rules_jsonl
from wqb.group_preparation import prepare_group_lanes


class GroupPreparationTests(unittest.TestCase):
    def setUp(self):
        """Input: test instance. Output: isolated official-format fictional vault fixture."""
        from tests.test_exploration_eligibility import ExplorationCertificationTests
        self.fixture = ExplorationCertificationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.paths = SimpleNamespace(run_root=self.fixture.root / 'runs', knowledge_root=self.fixture.vault)
        write_benchmark_rules_jsonl(benchmark_rules_path_for_knowledge(self.fixture.vault), default_benchmark_rules())

    def test_prepare_one_lane_only_certifies_and_stays_paused(self):
        result = prepare_group_lanes(self.paths, [self.fixture.resources], self.fixture.scope,
            dict(option_id='offline-option', title='Offline sourced exploration'),
            dict(enable_live_api=False, max_runtime_seconds=3600, max_recoveries=3))
        self.assertEqual(result['group']['desired_state'], 'paused')
        lane = result['group']['lanes'][0]
        self.assertEqual(result['certificates'][0]['owning_run']['run_id'], lane['run_id'])
        self.assertFalse((self.paths.run_root / lane['run_id'] / 'run_state.json').exists())
        self.assertFalse((self.paths.run_root / 'active_research_group.json').exists())

    def test_duplicate_data_does_not_create_fake_parallel_lanes(self):
        with self.assertRaises(ValueError):
            prepare_group_lanes(self.paths, [self.fixture.resources] * 2, self.fixture.scope,
                dict(option_id='offline-option'),
                dict(enable_live_api=False, max_runtime_seconds=3600, max_recoveries=3))
        self.assertFalse((self.paths.run_root / 'research_groups').exists())


if __name__ == '__main__':
    unittest.main()
