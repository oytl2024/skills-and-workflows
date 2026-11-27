from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class ResearchSkillMaintenanceTests(unittest.TestCase):
    def test_empty_reports_do_not_call_model_or_rebuild_inventories(self):
        from wqb.research_skill_maintenance import maintain_skill
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'skills/brain-research').mkdir(parents=True)
            (root/'skills/brain-research/SKILL.md').write_text('Research method', encoding='utf-8')
            result = maintain_skill(root, model_runner=lambda _:self.fail('no evidence for model'))
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['report_count'], 0)
            self.assertFalse((root/'machine').exists())
            self.assertFalse((root/'raw').exists())

    def test_learning_is_bound_to_reports_and_reuses_completed_job(self):
        from wqb.research_skill_maintenance import maintain_skill
        from wqb.research_tasks import create_task, update_task
        from wqb.research_task_report import publish_report
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace/'knowledge'
            (root/'skills/brain-research').mkdir(parents=True)
            (root/'skills/brain-research/SKILL.md').write_text('Research method', encoding='utf-8')
            task=create_task(workspace/'runs','test',dict(scope={}))
            update_task(workspace/'runs',task['task_id'],status='failed',reason='Unknown signature')
            path=publish_report(workspace/'runs',task['task_id'],root)
            def model(brief):
                """Input: compact report evidence. Output: method-only lesson referencing an actual report."""
                return dict(lessons=[dict(title='Uncertainty', lesson='An unknown signature is not evidence of no signal.',
                    report_paths=[path.relative_to(root).as_posix()])], limitations=['No measured Alpha.'])
            result=maintain_skill(root,model_runner=model)
            self.assertEqual(result['status'],'completed')
            self.assertIn('unknown signature', (root/'skills/brain-research/references/research-lessons.md').read_text(encoding='utf-8'))
            again=maintain_skill(root,model_runner=lambda _:self.fail('replayed learning task'))
            self.assertEqual(again['status'],'completed')
            second=create_task(workspace/'runs','second',dict(scope={}))
            update_task(workspace/'runs',second['task_id'],status='failed',reason='No measured result')
            publish_report(workspace/'runs',second['task_id'],root)
            def consolidate(brief):
                """Input: new evidence plus prior guidance. Output: consolidated method, not another appended copy."""
                self.assertIn('unknown signature',brief['prior_skill'])
                return model(brief)
            maintain_skill(root,model_runner=consolidate)
            body=(root/'skills/brain-research/references/research-lessons.md').read_text(encoding='utf-8')
            self.assertEqual(body.count('An unknown signature'),1)
