"""Known batch rejections are not permission to replay ambiguous requests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from wqb.research_group import create_group
from wqb.research_tasks import create_task, update_task, read_task


class BatchRecoveryTests(unittest.TestCase):
    def fixture(self, root):
        """Input: temporary root Path. Output: failed task/group/source/claims fixture."""
        from wqb.cli import simulation_identity_hash
        task = create_task(root, 'one', {'scope': {'region': 'ALL', 'delay': 1, 'universe': 'LARGE'}})
        runs = Path(task['runs_root'])
        group = create_group(runs, [dict(run_id='lane-0', plan_digest='a'*64)],
            dict(enable_live_api=True, max_runtime_seconds=3600, max_recoveries=3))
        update_task(root, task['task_id'], status='failed', reason='simulation identity already reserved or outcome unknown; reconcile before retry', group_dir=group['group_dir'])
        source = runs / 'source'
        source.mkdir()
        events, claims = [], {}
        for expression in ('rank(close)', '-rank(close)'):
            identity = simulation_identity_hash(expression, {'delay': 1})
            common = dict(expression=expression, settings={'delay': 1}, expression_hash=identity,
                attempt_id='b'*32, stage='run_field_batch_multi_submit',
                ai_plan_receipt=str(runs/'lane-0/runtime/research_plans/tree-plan.json'))
            events.extend([dict(common, event='SUBMISSION_STARTED'), dict(common, event='SUBMISSION_REJECTED')])
            claims[identity] = dict(group_id=group['group_id'], run_id='lane-0', submission_status='sent', status_code=400, progress_url='')
        (source/'simulation_events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        (source/'run_errors.jsonl').write_text(json.dumps(dict(stage='run_field_batch_multi_submit',status_code=400,payload_count=2))+'\n')
        shared = root/'research_groups'
        shared.mkdir(exist_ok=True)
        (shared/'simulation_reservations.json').write_text(json.dumps(claims))
        return task, source, claims

    def test_reconcile_and_reopen_only_confirmed_rejected_batch(self):
        from wqb.research_batch_recovery import reopen_rejected_batch_task
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'runs'
            task,source,claims=self.fixture(root)
            row=reopen_rejected_batch_task(root,task['task_id'],[source],authorization='user approved original two trees')
            self.assertEqual(row['status'],'running')
            saved=json.loads((root/'research_groups/simulation_reservations.json').read_text())
            self.assertTrue(all(c['submission_status']=='rejected_batch_400' for c in saved.values()))
            self.assertEqual(set(saved),set(claims))
            self.assertEqual(row['recovery_generation'],1)
            self.assertEqual(read_task(root,task['task_id'])['runs_root'],task['runs_root'])

    def test_reject_unknown_accepted_or_foreign_claim_without_partial_write(self):
        from wqb.research_batch_recovery import reopen_rejected_batch_task
        for change in ({'status_code':500},{'progress_url':'/simulations/x'}, {'run_id':'foreign'}):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)/'runs'
                task,source,claims=self.fixture(root)
                next(iter(claims.values())).update(change)
                path=root/'research_groups/simulation_reservations.json'
                path.write_text(json.dumps(claims))
                with self.assertRaises(ValueError):
                    reopen_rejected_batch_task(root,task['task_id'],[source],authorization='approved')
                self.assertEqual(json.loads(path.read_text()),claims)
                self.assertEqual(read_task(root,task['task_id'])['status'],'failed')

    def test_response_diagnostic_is_bounded_and_redacted(self):
        from wqb.cli import record_recoverable_network_error
        recorder=Mock()
        error=RuntimeError('bad request')
        error.response=Mock(status_code=400, headers={}, text=json.dumps({'detail':'invalid universe','password':'private'}))
        record_recoverable_network_error(recorder,'submit',error)
        row=recorder.append_jsonl.call_args.args[1]
        self.assertIn('invalid universe',row['response_detail'])
        self.assertNotIn('private',row['response_detail'])

    def test_retry_uses_frozen_settings_without_unrelated_generation_defaults(self):
        from wqb.cli import retry_planned_candidates
        recorder=Mock()
        recorder.read_jsonl.side_effect=lambda name: [dict(expression='rank(close)',expression_hash='a'*64,
            settings={'delay':1})] if name=='planned_candidates.jsonl' else []
        with patch('wqb.cli.submitted_or_terminal_hashes',return_value=set()), \
                patch('wqb.cli.build_settings',side_effect=AssertionError('frozen settings must be reused')), \
                patch('wqb.cli.source_benchmark_run',return_value=None), \
                patch('wqb.cli.submit_candidate_payloads',return_value=[]) as submit:
            retry_planned_candidates(Mock(),recorder,{},submit_mode='serial')
        self.assertEqual(submit.call_args.args[2][0]['settings'],{'delay':1})

    def test_recovered_terminal_report_replaces_stale_failure_once(self):
        from wqb.research_batch_recovery import reopen_rejected_batch_task
        from wqb.research_task_report import publish_report
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'runs'
            task,source,_=self.fixture(root)
            report=publish_report(root,task['task_id'],Path(tmp)/'knowledge')
            old=report.read_text(encoding='utf-8')
            reopen_rejected_batch_task(root,task['task_id'],[source],authorization='approved original trees')
            update_task(root,task['task_id'],status='completed_no_candidate',reason='search completed')
            self.assertEqual(publish_report(root,task['task_id'],Path(tmp)/'knowledge'),report)
            new=report.read_text(encoding='utf-8')
            self.assertNotEqual(new,old)
            self.assertIn('completed_no_candidate',new)
            publish_report(root,task['task_id'],Path(tmp)/'knowledge')
            self.assertEqual(report.read_text(encoding='utf-8'),new)

    def test_release_only_matching_preimport_hold_preserves_control(self):
        from wqb.research_batch_recovery import reopen_rejected_batch_task,release_batch_recovery_holds
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'runs'
            task,source,_=self.fixture(root)
            reopen_rejected_batch_task(root,task['task_id'],[source],authorization='approved')
            lane=Path(task['runs_root'])/'lane-0'
            case=dict(stage='scout_seed',action='stage_failed',status='awaiting_maintenance_confirmation')
            original=dict(desired_state='running',max_runtime_seconds=3600,simulation_attempts=2,recovery_case=case)
            (lane/'runtime_control.json').write_text(json.dumps(original))
            (lane/'runtime_status.json').write_text(json.dumps(dict(recovery_case=case,last_result=dict(
                pause_reason='checked research results require completed tree: missing import'))))
            release_batch_recovery_holds(root,task['task_id'],authorization='approved original trees')
            saved=json.loads((lane/'runtime_control.json').read_text())
            self.assertEqual(saved,{key:value for key,value in original.items() if key!='recovery_case'})
            # Real runtime controls merge the case stored only in runtime_status.
            status_only=dict(original)
            status_only.pop('recovery_case')
            (lane/'runtime_control.json').write_text(json.dumps(status_only))
            (lane/'runtime_status.json').write_text(json.dumps(dict(recovery_case=case,last_result=dict(
                pause_reason='checked research results require completed tree: missing import'))))
            release_batch_recovery_holds(root,task['task_id'],authorization='approved')
            self.assertEqual(json.loads((lane/'runtime_status.json').read_text())['recovery_case'],{})
            original['recovery_case']=dict(case,stage='repair')
            (lane/'runtime_control.json').write_text(json.dumps(original))
            with self.assertRaisesRegex(ValueError,'unrelated'):
                release_batch_recovery_holds(root,task['task_id'],authorization='approved')
            self.assertEqual(json.loads((lane/'runtime_control.json').read_text()),original)


if __name__ == '__main__':
    unittest.main()
