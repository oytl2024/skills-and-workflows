import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_workflow_stage_outcomes import checked_alpha, write_rows
from wqb.discovery_runtime import DiscoveryRuntimeExecutor


class DiscoveryRuntimeTests(unittest.TestCase):
    def test_completed_partial_discovery_restarts_without_platform_requests(self):
        """Input: checked4-row durable Discovery plan. Output: assertions. Partial queues are complete, not pending forever."""
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / 'run_manifest.json').write_text(json.dumps({'selected_scope': {
                'region': 'USA', 'delay': 1, 'universe': 'TOP3000'}}))
            schedule = run / 'stages/schedule/research_schedule.json'
            schedule.parent.mkdir(parents=True)
            schedule.write_text(json.dumps({'template_matches': [{'field_id': 'cash'}]}))
            source = run / 'stages/batch_generation/source'
            rows = [checked_alpha('weak', alpha_id=f'child-{i}', expression_hash=f'hash-{i}') for i in range(4)]
            write_rows(source, rows)
            (source / 'planned_candidates.jsonl').write_text(''.join(
                json.dumps({'expression_hash': row['expression_hash']}) + '\n' for row in rows))
            with patch('wqb.cli.build_client') as client, patch('wqb.cli.complete_in_flight') as recover, \
                 patch('wqb.cli.retry_planned') as retry:
                first = DiscoveryRuntimeExecutor({})(run, checked_alpha('repairable'))
                second = DiscoveryRuntimeExecutor({})(run, checked_alpha('repairable'))
            self.assertEqual(len(first), 4)
            self.assertEqual(first, second)
            client.assert_not_called()
            recover.assert_not_called()
            retry.assert_not_called()

    def test_interrupted_plan_publication_never_exposes_partial_queue(self):
        """Input: crash before atomic plan move. Output: assertions. Restart publishes the complete30 without a partial prefix."""
        from wqb.recorder import RunRecorder
        with tempfile.TemporaryDirectory() as tmp:
            recorder = RunRecorder(tmp)
            plan = [{'expression_hash': f'h{i}', 'expression': f'rank(cash)+{i}'} for i in range(30)]
            with patch.object(Path, 'replace', side_effect=OSError('interrupted publication')):
                with self.assertRaises(OSError):
                    recorder.publish_plan(plan)
            self.assertFalse((Path(tmp) / 'planned_candidates.jsonl').exists())
            recorder.publish_plan(plan)
            self.assertEqual(recorder.read_jsonl('planned_candidates.jsonl'), plan)
            recorder.publish_plan(plan)
            self.assertEqual(len(recorder.read_jsonl('planned_candidates.jsonl')), 30)

    def test_complete_source_replay_makes_no_client_or_recovery_requests(self):
        """Input: durable30 checked Discovery identities. Output: assertions. Restart reads evidence without authentication or POST."""
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / 'run_manifest.json').write_text(json.dumps({'selected_scope': {
                'region': 'USA', 'delay': 1, 'universe': 'TOP3000'}}))
            schedule = run / 'stages/schedule/research_schedule.json'
            schedule.parent.mkdir(parents=True)
            schedule.write_text(json.dumps({'template_matches': [{'field_id': 'cash'}]}))
            source = run / 'stages/batch_generation/source'
            rows = [checked_alpha('weak', alpha_id=f'child-{i}', expression_hash=f'hash-{i}') for i in range(30)]
            write_rows(source, rows)
            (source / 'planned_candidates.jsonl').write_text(''.join(
                json.dumps({'expression_hash': row['expression_hash']}) + '\n' for row in rows))
            parent = checked_alpha('repairable')
            with patch('wqb.cli.build_client') as client, patch('wqb.cli.complete_in_flight') as recover, \
                    patch('wqb.cli.retry_planned') as retry:
                result = DiscoveryRuntimeExecutor({})(run, parent)
            self.assertEqual(len(result), 30)
            self.assertEqual(result[0]['parent_alpha_id'], parent['alpha_id'])
            client.assert_not_called()
            recover.assert_not_called()
            retry.assert_not_called()
