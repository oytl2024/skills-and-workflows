import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_hypothesis_selection import selection_fixture, candidate_for
from tests.test_workflow_stage_adapters import write_start_artifacts
from wqb import generator, research_planning, workflow_stage_adapters as stages
from wqb import source_bridge, research_rounds


def pipeline_fixture(root):
    """Input: temp root Path. Output: snapshot/config/run tuple. Create offline frozen multi-input research inputs."""
    snapshot = selection_fixture()
    candidate_for(snapshot, 'reversal', mechanism='Attention reversal.', skeleton='-rank({flow} / {liability})')
    snapshot.update(hypothesis_binding_version=2, artifact_binding_version=2)
    config = dict(instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000', decay=0,
                  neutralization='INDUSTRY', truncation=0.08, pasteurization='ON', unit_handling='VERIFY',
                  nan_handling='OFF', language='FASTEXPR', max_alphas_per_round=7)
    run = root / 'run'
    run.mkdir()
    (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)), encoding='utf-8')
    return snapshot, config, run


class HypothesisPipelineTests(unittest.TestCase):
    def test_paired_measured_parent_enters_existing_repair_without_resource_downgrade(self):
        from tests.test_hypothesis_selection import paired_selection_fixture
        from tests.test_workflow_stage_outcomes import checked_alpha
        from wqb.repair_runtime import RepairRuntimeExecutor
        from wqb.cli import simulation_identity_hash
        from wqb.models import CheckSummary
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, experiments = paired_selection_fixture(root)
            run = root / 'run'
            run.mkdir()
            manifest = run / 'run_manifest.json'
            manifest.write_text(json.dumps(dict(start_snapshot=snapshot, selected_scope=snapshot['selected_scope'])))
            before = manifest.read_bytes()
            arm = experiments[0]['arms'][1]
            parent = dict(checked_alpha('repairable'), expression=arm['binding']['bound_expression'], settings=arm['settings'])
            parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
            actions = [dict(parent_hash=parent['expression_hash'], reason='LOW_FITNESS', action_type='reduce_turnover')]
            client = Mock()
            with patch('wqb.cli.require_readiness_gate'), patch('wqb.cli.build_client', return_value=client), patch(
                    'wqb.cli.submit_simulation', return_value='/simulations/offline-repair') as submit, patch(
                    'wqb.cli.poll_simulation', return_value=dict(alpha='repaired')), patch(
                    'wqb.cli.fetch_check_summary', return_value=CheckSummary('repaired', True, [], [], [], dict(sharpe=1.8, fitness=1.2))), patch(
                    'wqb.cli.benchmark_fields_for_record', return_value={}):
                executor = RepairRuntimeExecutor(dict(knowledge_root=str(root / 'knowledge')), enable_live_api=True)
                first = executor(run, parent, actions, 1)
                self.assertEqual(executor(run, parent, actions, 1), first)
                self.assertEqual(submit.call_count, 1)
            self.assertEqual(len(first), 1)
            self.assertEqual(first[0]['expression'], parent['expression'])
            self.assertEqual(first[0]['parent_expression_hash'], parent['expression_hash'])
            self.assertEqual(manifest.read_bytes(), before)

    def test_paired_measured_seed_enters_existing_discovery_optimization_and_replays(self):
        from tests.test_hypothesis_selection import paired_selection_fixture
        from tests.test_workflow_stage_outcomes import checked_alpha
        from wqb.discovery_runtime import DiscoveryRuntimeExecutor
        from wqb.cli import simulation_identity_hash, _hypothesis_source_selection
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, experiments = paired_selection_fixture(root)
            run = root / 'run'
            run.mkdir()
            (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot,
                selected_scope=snapshot['selected_scope'])))
            settings = experiments[0]['arms'][0]['settings']
            config = dict(settings, instrument_type=settings['instrumentType'], unit_handling=settings['unitHandling'],
                nan_handling=settings['nanHandling'], max_alphas_per_round=3, knowledge_root=str(root / 'knowledge'))
            stages.schedule_research_stage(root / 'knowledge', run, 'option-1')
            scout = research_planning.prepare_source_plan(run, config, {}, 'now')
            binding = scout['scheduled_hypotheses'][1]
            parent = {**checked_alpha('repairable'), **generator.hypothesis_candidate_metadata(snapshot, binding, scout['ai_plan_receipt']),
                'expression': binding['bound_expression'], 'settings': binding['settings'],
                'expression_hash': simulation_identity_hash(binding['bound_expression'], binding['settings'])}
            seed_path = run / 'stages/batch_generation/seed.json'
            seed_path.parent.mkdir(parents=True)
            seed_path.write_text(json.dumps(dict(parent=parent)))
            def fake_batch(client, recorder, consumed, **kwargs):
                """Input: existing executor handoff. Output: None. Verify real generation, then store fictional measured children."""
                self.assertEqual(consumed['hypothesis_execution_kind'], 'discovery')
                _hypothesis_source_selection(consumed)
                candidates = generator.generate_hypothesis_candidates(snapshot, consumed['scheduled_hypotheses'], 30)
                self.assertEqual(len(candidates), 15)
                planned = []
                for index, row in enumerate(consumed['scheduled_hypotheses']):
                    self.assertEqual(row['bound_expression'], parent['expression'])
                    audit = generator.hypothesis_candidate_metadata(snapshot, row, consumed['ai_plan_receipt'])
                    planned.append(dict(expression=row['bound_expression'], settings=row['settings'],
                        expression_hash=simulation_identity_hash(row['bound_expression'], row['settings']), **audit))
                recorder.publish_plan(planned)
                for index, row in enumerate(planned):
                    recorder.append_jsonl('all_alphas.jsonl', {**checked_alpha('weak', alpha_id=f'discovery-{index}'), **row})
            with patch('wqb.cli.build_client', return_value=Mock()), patch('wqb.cli.require_readiness_gate'), patch(
                    'wqb.cli.run_field_batch', side_effect=fake_batch) as batch, patch(
                    'wqb.research_planning._hypothesis_pool', side_effect=AssertionError('Scout grid')):
                executor = DiscoveryRuntimeExecutor(config)
                first = executor(run, parent)
                self.assertEqual(executor(run, parent), first)
                self.assertEqual(batch.call_count, 1)

    def test_paired_schedule_source_bridge_and_cli_preserve_complete_arm_sidecars(self):
        from tests.test_hypothesis_selection import paired_selection_fixture
        from wqb.cli import _hypothesis_source_selection
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, experiments = paired_selection_fixture(root)
            run = root / 'run'
            run.mkdir()
            (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)))
            stages.schedule_research_stage(root / 'knowledge', run, 'option-1')
            metadata = source_bridge._source_batch_metadata(run)
            self.assertTrue(metadata['local_construction_ready'], metadata)
            settings = experiments[0]['arms'][0]['settings']
            config = dict(settings, instrument_type=settings['instrumentType'], unit_handling=settings['unitHandling'],
                nan_handling=settings['nanHandling'], max_alphas_per_round=3)
            plan = research_planning.prepare_source_plan(run, config, metadata, 'now')
            _hypothesis_source_selection(plan)
            for binding in plan['scheduled_hypotheses']:
                audit = generator.hypothesis_candidate_metadata(snapshot, binding, plan['ai_plan_receipt'])
                self.assertEqual(len(audit['experiment_arms']), 1)
                self.assertEqual(audit['experiment_arms'][0]['experiment_id'], experiments[0]['experiment_id'])
            altered = dict(plan, experiment_sidecar_path='outside')
            with self.assertRaises(research_planning.ResearchPlanningBlocked):
                _hypothesis_source_selection(altered)

    def test_zero_pool_does_not_invoke_model_and_local_stop_prevents_planning(self):
        from wqb.runtime_control import RuntimePaused
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, config, run = pipeline_fixture(Path(tmp))
            snapshot['data_ledger_rows'] = []
            (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)))
            with patch('wqb.research_planning.run_ai_checkpoint') as model:
                with self.assertRaises(research_planning.ResearchVariantsExhausted):
                    research_planning.prepare_hypothesis_plan(run, dict(config, ai_executor='codex'), {}, 'now')
            model.assert_not_called()
            (run / 'runtime_control.json').write_text(json.dumps(dict(max_simulations=150, desired_state='paused')))
            (run / 'runtime_status.json').write_text(json.dumps(dict(simulation_attempts=143)))
            with self.assertRaises(RuntimePaused):
                research_planning.prepare_hypothesis_plan(run, config, {}, 'restart')

    def test_v2_scout_to_discovery_preserves_measured_seed_and_all_parent_slots(self):
        from unittest.mock import Mock
        from wqb.discovery_runtime import DiscoveryRuntimeExecutor
        from tests.test_workflow_stage_outcomes import checked_alpha
        from wqb.recorder import RunRecorder
        from wqb.cli import simulation_identity_hash
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, config, run = pipeline_fixture(Path(tmp))
            plan = research_planning.prepare_hypothesis_plan(run, config, {}, 'now')
            binding = next(row for row in plan['scheduled_hypotheses'] if row['hypothesis_id'] == 'reversal')
            parent = {**checked_alpha('repairable'), **generator.hypothesis_candidate_metadata(snapshot, binding, plan['ai_plan_receipt']),
                      'expression': binding['bound_expression'], 'settings': binding['settings'],
                      'expression_hash': simulation_identity_hash(binding['bound_expression'], binding['settings'])}
            manifest = dict(start_snapshot=snapshot, selected_scope=snapshot['selected_scope'])
            (run / 'run_manifest.json').write_text(json.dumps(manifest))
            schedule_path = run / 'stages/schedule/research_schedule.json'
            schedule_path.parent.mkdir(parents=True)
            schedule_path.write_text(json.dumps(dict(template_matches=[dict(field_id='cash', dataset_id='fundamentals',
                template_id='cash-debt', hypothesis='First unrelated direction.', skeleton='rank({field})')])))
            seed = run / 'stages/batch_generation/seed.json'
            seed.parent.mkdir(parents=True)
            seed.write_text(json.dumps(dict(parent=parent)))
            def fake_batch(client, recorder, consumed, **kwargs):
                """Input: fake platform batch arguments. Output: None. Consume actual generator and publish fake checked evidence."""
                self.assertTrue(Path(consumed['ai_plan_receipt']).exists())
                self.assertEqual(consumed['hypothesis_execution_kind'], 'discovery')
                rows = generator.generate_hypothesis_candidates(consumed['hypothesis_snapshot'], consumed['scheduled_hypotheses'], 30)
                self.assertTrue(all(row.expression == parent['expression'] for row in rows))
                planned = []
                for i, row in enumerate(rows):
                    item = consumed['scheduled_hypotheses'][i]
                    self.assertEqual(item['bindings'], binding['bindings'])
                    planned.append(dict(expression=row.expression, settings=row.settings,
                        expression_hash=simulation_identity_hash(row.expression, row.settings),
                        **generator.hypothesis_candidate_metadata(snapshot, item, consumed['ai_plan_receipt'])))
                recorder.publish_plan(planned)
                for i, row in enumerate(planned):
                    recorder.append_jsonl('all_alphas.jsonl', {**checked_alpha('weak', alpha_id='child-' + str(i)), **row})
            with patch('wqb.research_planning.run_ai_checkpoint') as model, patch('wqb.cli.build_client', return_value=Mock()), patch(
                    'wqb.cli.require_readiness_gate'), patch('wqb.cli.run_field_batch', side_effect=fake_batch) as batch:
                first = DiscoveryRuntimeExecutor(config)(run, parent)
                second = DiscoveryRuntimeExecutor(config)(run, parent)
            self.assertEqual(first, second)
            self.assertTrue(all(row['hypothesis_id'] == 'reversal' and row['parent_expression_hash'] == parent['expression_hash'] for row in first))
            self.assertEqual(batch.call_count, 1)
            model.assert_not_called()

    def test_catalog_multiple_explicit_field_groups_preserve_binder_ambiguity_guard(self):
        from wqb.template_binding import bind_template, TemplateBindingError
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, config, run = pipeline_fixture(Path(tmp))
            other = copy.deepcopy(snapshot['data_ledger_rows'])
            for row in other:
                row['dataset_id'] = 'other_fundamentals'
                row['field_id'] += '_other'
            snapshot['data_ledger_rows'].extend(other)
            with self.assertRaises(TemplateBindingError):
                bind_template(snapshot['template_rows'][0], snapshot['data_ledger_rows'], snapshot['operator_rows'], snapshot['selected_scope'])
            (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)))
            planned = research_planning.prepare_hypothesis_plan(run, dict(config, max_alphas_per_round=30), {}, 'now')
            rows = planned['scheduled_hypotheses']
            self.assertEqual({item['bindings']['flow']['dataset_id'] for item in rows},
                             {'fundamentals', 'other_fundamentals'})
            self.assertTrue(all({value['dataset_id'] for value in row['bindings'].values()} in (
                {'fundamentals'}, {'other_fundamentals'}) for row in rows))
            generated = generator.generate_hypothesis_candidates(snapshot, rows, 30)
            self.assertEqual(len(generated), 30)

    def test_original_remaining_budget_bounds_initial_plan_without_mutating_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, config, run = pipeline_fixture(Path(tmp))
            control = dict(max_simulations=150, desired_state='running', max_runtime_seconds=3600,
                           max_recoveries=3, enable_live_api=False, request_revision='approved')
            (run / 'runtime_control.json').write_text(json.dumps(control))
            (run / 'runtime_status.json').write_text(json.dumps(dict(simulation_attempts=143)))
            before = (run / 'runtime_control.json').read_bytes()
            planned = research_planning.prepare_hypothesis_plan(run, dict(config, max_alphas_per_round=30), {}, 'now')
            self.assertEqual(len(planned['scheduled_hypotheses']), 7)
            self.assertEqual(planned['max_alphas_per_round'], 7)
            self.assertEqual((run / 'runtime_control.json').read_bytes(), before)

    def test_previously_consumed_simulation_identity_is_excluded_and_exhaustion_is_durable(self):
        from wqb.cli import simulation_identity_hash
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, config, run = pipeline_fixture(Path(tmp))
            pool = research_planning._hypothesis_pool(snapshot, generator.build_settings(config), None)
            history = Path(tmp) / 'history'
            history.mkdir()
            (history / 'simulation_events.jsonl').write_text(''.join(json.dumps(dict(
                expression_hash=simulation_identity_hash(row['bound_expression'], row['settings']), event='SUBMITTED')) + '\n' for row in pool))
            for now in ['now', 'restart']:
                with self.assertRaises(research_planning.ResearchVariantsExhausted):
                    research_planning.prepare_hypothesis_plan(run, dict(config, run_root=tmp), {}, now)

    def test_real_checkpoint_and_worker_consume_multihypothesis_brief_via_fake_cli(self):
        from subprocess import CompletedProcess
        from wqb.codex_ai_worker import run_worker
        with tempfile.TemporaryDirectory() as tmp:
            _, config, run = pipeline_fixture(Path(tmp))
            def cli_reply(argv, **kwargs):
                """Input: fake Codex CLI argv. Output: process result. Verify strict worker schema and return indexed binding."""
                self.assertIn('model_reasoning_effort=medium', argv)
                self.assertIn('read-only', argv)
                self.assertLess(len(argv[-1].encode()), 12000)
                self.assertIn('supporting_evidence', argv[-1])
                schema = json.loads(Path(argv[argv.index('--output-schema') + 1]).read_text())
                self.assertIn('decision', schema['properties'])
                self.assertFalse(schema['properties']['decision']['additionalProperties'])
                pool = json.loads(next((run / 'runtime/research_plans').glob('*.input.json')).read_text())['allowed_bindings']
                row = next(row for row in pool if row['hypothesis_id'] == 'reversal')
                answer = dict(summary='Offline bounded choice.', decision=dict(selected_bindings=[dict(
                    binding_id=row['candidate_id'], hypothesis_id=row['hypothesis_id'], hypothesis_version=1)]))
                Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(answer))
                return CompletedProcess(argv, 0, '', '')
            def checkpoint_process(argv, timeout_seconds):
                """Input: checkpoint worker argv/timeout. Output: process result. Execute real worker with only final CLI faked."""
                run_worker(Path(argv[-2]), Path(argv[-1]))
                return CompletedProcess(argv, 0, '', '')
            with patch('wqb.ai_checkpoints._run_cancellable', side_effect=checkpoint_process), patch(
                    'wqb.codex_ai_worker.shutil.which', return_value='fake-codex'), patch(
                    'wqb.codex_ai_worker.subprocess.run', side_effect=cli_reply) as cli:
                first = research_planning.prepare_hypothesis_plan(run, dict(config, ai_executor='codex'), {}, 'now')
                second = research_planning.prepare_hypothesis_plan(run, dict(config, ai_executor='codex'), {}, 'restart')
            self.assertEqual(first, second)
            self.assertEqual(first['scheduled_hypotheses'][0]['hypothesis_id'], 'reversal')
            self.assertEqual(cli.call_count, 1)

    def test_model_receives_short_cards_and_hash_backed_full_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, config, run = pipeline_fixture(Path(tmp))
            def fake_model(directory, identifier, argv, **kwargs):
                """Input: fake checkpoint arguments. Output: completed decision dict. Inspect actual evidence projection."""
                from wqb.ai_checkpoints import load_ai_checkpoints
                checkpoint = load_ai_checkpoints(directory)[-1]
                brief_path = Path(checkpoint['evidence_paths'][0])
                brief = json.loads(brief_path.read_text())
                self.assertNotIn('allowed_bindings', brief)
                self.assertEqual(len(brief['hypotheses']), 2)
                self.assertTrue(all(len(row['hypothesis_card']) == 7 for row in brief['hypotheses']))
                self.assertLess(len(json.dumps(brief).encode()), 9000)
                ref = brief['supporting_evidence']
                pack_path = run / ref['path']
                self.assertEqual(hashlib.sha256(pack_path.read_bytes()).hexdigest(), ref['sha256'])
                pool = json.loads(pack_path.read_text())['allowed_bindings']
                self.assertGreater(len(json.dumps(pool).encode()), 12000)
                row = pool[0]
                return dict(status='completed', decision=dict(selected_bindings=[dict(
                    binding_id=row['candidate_id'], hypothesis_id=row['hypothesis_id'],
                    hypothesis_version=row['hypothesis_version'])]))
            with patch('wqb.research_planning.run_ai_checkpoint', side_effect=fake_model):
                research_planning.prepare_hypothesis_plan(run, dict(config, ai_executor='codex'), {}, 'now')

    def test_v2_source_metadata_keeps_all_slots_and_rejects_unrelated_binding_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, config, run = pipeline_fixture(Path(tmp))
            matches = []
            from wqb.template_binding import bind_template
            for template in snapshot['template_rows']:
                binding = bind_template(template, snapshot['data_ledger_rows'], snapshot['operator_rows'], snapshot['selected_scope'])
                matches.append(dict(template_id=template['template_id'], hypothesis_id=template['hypothesis_id'],
                    hypothesis_version=template['hypothesis_version'], skeleton=template['skeleton'],
                    hypothesis=template['hypothesis'], hypothesis_binding=binding))
            path = run / 'stages/schedule/research_schedule.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(dict(hypothesis_binding_version=2, template_matches=matches,
                selected_data=snapshot['data_ledger_rows'], batch_size=7)))
            metadata = source_bridge._source_batch_metadata(run)
            self.assertTrue(metadata['local_construction_ready'], metadata)
            self.assertEqual(len(metadata['hypothesis_allowed_refs']), 2)
            self.assertEqual({row['field_id'] for row in metadata['source_provenance']}, {'cash', 'debt'})
            planned = research_planning.prepare_hypothesis_plan(run, config, metadata, 'now')
            source = Path(tmp) / 'source'
            source.mkdir()
            audit = {**metadata, 'hypothesis_bindings': planned['hypothesis_bindings'],
                     'ai_plan_receipt': planned['ai_plan_receipt']}
            (source / 'run_meta.jsonl').write_text(json.dumps(audit) + '\n')
            self.assertTrue(source_bridge._source_is_compatible(source, metadata))
            # Consuming the last simulation changes remaining quota, not the identity of existing authorized evidence.
            (run / 'runtime_control.json').write_text(json.dumps(dict(max_simulations=7)))
            (run / 'runtime_status.json').write_text(json.dumps(dict(simulation_attempts=7)))
            remaining_metadata = source_bridge._source_batch_metadata(run)
            self.assertEqual(remaining_metadata['max_alphas_per_round'], 0)
            self.assertTrue(source_bridge._source_is_compatible(source, remaining_metadata))
            audit['hypothesis_bindings'][0]['bindings']['flow']['field_id'] = 'outside'
            (source / 'run_meta.jsonl').write_text(json.dumps(audit) + '\n')
            self.assertFalse(source_bridge._source_is_compatible(source, metadata))

    def test_v2_alternate_rebinds_complete_frozen_metadata_not_legacy_field_match(self):
        snapshot = selection_fixture()
        a = candidate_for(snapshot, 'a')
        b = candidate_for(snapshot, 'b', skeleton='-rank({flow} / {liability})')
        snapshot['hypothesis_binding_version'] = 2
        matches = [dict(template_id=row['template_id'], hypothesis_id=row['hypothesis_id'],
            hypothesis_version=row['hypothesis_version'], hypothesis_binding={key: row[key] for key in (
                'bound_expression', 'bindings', 'operator_provenance', 'operator_call_count')}) for row in [a, b]]
        schedule = {**snapshot['selected_scope'], 'template_matches': matches}
        manifest = dict(start_snapshot=snapshot, selected_scope=snapshot['selected_scope'])
        result = research_rounds._select_next_match(schedule, manifest, [research_rounds._identity(matches[0])])
        self.assertEqual(result, matches[1])
        matches[1]['hypothesis_binding']['bindings']['flow']['field_id'] = 'outside'
        self.assertEqual(research_rounds._select_next_match(schedule, manifest, [research_rounds._identity(matches[0])]), {})

    def test_plan_is_consumed_by_real_generator_and_persisted_before_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, config, run = pipeline_fixture(Path(tmp))
            self.assertTrue(hasattr(research_planning, 'prepare_hypothesis_plan'), 'Missing consumed Task6 planner')
            patch_config = research_planning.prepare_hypothesis_plan(run, config, {}, 'now')
            self.assertEqual(patch_config['max_alphas_per_round'], 7)
            self.assertTrue(Path(patch_config['ai_plan_receipt']).exists())
            rows = generator.generate_hypothesis_candidates(snapshot, patch_config['scheduled_hypotheses'], 7)
            self.assertEqual(len(rows), 7)
            self.assertEqual({row.expression for row in rows}, {'rank(cash / debt)', '-rank(cash / debt)'})
            self.assertTrue(all(row.settings['region'] == 'USA' for row in rows))
            self.assertEqual(len({(row.expression, json.dumps(row.settings, sort_keys=True)) for row in rows}), 7)
            self.assertEqual(patch_config['hypothesis_bindings'], patch_config['scheduled_hypotheses'])
            from wqb.research_record import empty_research_record, record_alpha_result, research_record_to_dict
            record = empty_research_record('offline', 'Audit lineage')
            for binding in patch_config['scheduled_hypotheses']:
                audit = generator.hypothesis_candidate_metadata(snapshot, binding, patch_config['ai_plan_receipt'])
                self.assertEqual(set(audit['bindings']), {'flow', 'liability'})
                self.assertEqual({row['field_id'] for row in audit['source_provenance']}, {'cash', 'debt'})
                record = record_alpha_result(record, dict(expression=binding['bound_expression'],
                    settings=binding['settings'], hard_pass=False, **audit))
            saved = research_record_to_dict(record)['backtest']
            self.assertEqual({row['hypothesis_id'] for row in saved}, {'resilience', 'reversal'})
            self.assertTrue(all(row['hypothesis_version'] == 1 and row['operator_provenance'] for row in saved))

    def test_restart_reuses_exact_plan_and_changed_inputs_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, config, run = pipeline_fixture(Path(tmp))
            self.assertTrue(hasattr(research_planning, 'prepare_hypothesis_plan'))
            first = research_planning.prepare_hypothesis_plan(run, config, {}, 'now')
            self.assertEqual(first, research_planning.prepare_hypothesis_plan(run, config, {}, 'later'))
            audit = json.loads(Path(first['ai_plan_receipt']).read_text())
            self.assertEqual(audit['consumption_audit']['cache_status'], 'replayed')
            quality = audit['config_patch']['hypothesis_plan_quality']
            self.assertGreater(quality['binding_pass_count'], 0)
            self.assertGreaterEqual(quality['binding_attempt_count'], quality['binding_pass_count'])
            self.assertEqual(quality['selection']['mechanism_family_count'], 2)
            with self.assertRaises(research_planning.ResearchPlanningBlocked):
                research_planning.prepare_hypothesis_plan(run, dict(config, truncation=0.1), {}, 'later')
            receipt = Path(first['ai_plan_receipt'])
            payload = json.loads(receipt.read_text())
            payload['config_patch']['scheduled_hypotheses'][0]['bound_expression'] = 'rank(outside)'
            receipt.write_text(json.dumps(payload))
            with self.assertRaises(research_planning.ResearchPlanningBlocked):
                research_planning.prepare_hypothesis_plan(run, config, {}, 'later')

    def test_model_binding_ids_are_consumed_and_cached_without_arbitrary_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, config, run = pipeline_fixture(Path(tmp))
            self.assertTrue(hasattr(research_planning, 'prepare_hypothesis_plan'))
            def fake_model(directory, identifier, argv, **kwargs):
                """Input: checkpoint args. Output: fake decision dict selecting one frozen alternative binding."""
                evidence = next((run / 'runtime/research_plans').glob('*.input.json'))
                pool = json.loads(evidence.read_text())['allowed_bindings']
                choice = next(row for row in pool if row['hypothesis_id'] == 'reversal')
                return dict(status='completed', summary='Offline test recommendation.', decision=dict(selected_bindings=[
                    dict(binding_id=choice['candidate_id'], hypothesis_id=choice['hypothesis_id'],
                         hypothesis_version=choice['hypothesis_version'])]))
            with patch('wqb.research_planning.run_ai_checkpoint', side_effect=fake_model) as model:
                first = research_planning.prepare_hypothesis_plan(run, dict(config, ai_executor='codex'), {}, 'now')
                second = research_planning.prepare_hypothesis_plan(run, dict(config, ai_executor='codex'), {}, 'later')
            self.assertEqual(first, second)
            self.assertEqual(len(first['scheduled_hypotheses']), 1)
            self.assertEqual(first['scheduled_hypotheses'][0]['hypothesis_id'], 'reversal')
            self.assertEqual(model.call_count, 1)

    def test_failed_or_unknown_ai_choice_is_durable_blocker_without_repeat(self):
        for result in [dict(status='failed'), dict(status='completed', decision=dict(selected_bindings=[
                dict(binding_id='outside', hypothesis_id='outside', hypothesis_version=1)])),
                dict(status='completed', decision=dict(selected_bindings=[], code='arbitrary'))]:
            with self.subTest(result=result), tempfile.TemporaryDirectory() as tmp:
                _, config, run = pipeline_fixture(Path(tmp))
                self.assertTrue(hasattr(research_planning, 'prepare_hypothesis_plan'))
                with patch('wqb.research_planning.run_ai_checkpoint', return_value=result) as model:
                    for now in ['now', 'restart']:
                        with self.assertRaises(research_planning.ResearchPlanningBlocked):
                            research_planning.prepare_hypothesis_plan(run, dict(config, ai_executor='codex'), {}, now)
                self.assertEqual(model.call_count, 1)

    def test_generator_rejects_tampered_binding_instead_of_silent_partial_plan(self):
        snapshot = selection_fixture()
        candidate = candidate_for(snapshot, 'a')
        candidate['bindings']['flow']['field_id'] = 'outside'
        self.assertTrue(hasattr(generator, 'generate_hypothesis_candidates'))
        with self.assertRaises(ValueError):
            generator.generate_hypothesis_candidates(snapshot, [candidate], 7)


class HypothesisSnapshotTests(unittest.TestCase):
    def paired_knowledge(self, root, count=1, shared_baseline=False):
        """Input: temporary Path. Output: vault/scope tuple. Publish only fictional reviewed compiler artifacts."""
        from tests.test_hypothesis_design_acceptance import HypothesisResourceAuditTests
        from wqb.hypothesis_design import compile_hypothesis_design, validate_hypothesis_design
        from wqb.semantic_compilation import _design_versions
        from wqb.semantic_contracts import SemanticPolicy
        from wqb.semantic_publication import stage_semantic_release, publish_semantic_release
        design, resources, scope = HypothesisResourceAuditTests().page_pair_fixture()
        knowledge, _ = self.make_knowledge(root)
        decisions = knowledge / 'machine/decisions'
        decisions.mkdir()
        (knowledge / 'wiki/70_decisions/research_option_cards.jsonl').rename(decisions / 'research_option_cards.jsonl')
        (knowledge / 'wiki/70_decisions').rmdir()
        (knowledge / 'wiki/10_foundations/activity_snapshot.md').rename(knowledge / 'wiki/10_platform_rules.md')
        (knowledge / 'wiki/10_foundations').rmdir()
        for row in resources['field_rows']:
            row.update(coverage=1, source_quality='platform_raw_capture', coverage_status='measured_raw',
                       source_updated_at='2026-10-13', compatible_template_ids=[])
        for row in resources['operator_rows']:
            row['semantic_status'] = 'reviewed'
        result = compile_hypothesis_design(design, resources, scope)
        self.assertEqual(result['status'], 'compiled', result)
        refs = []
        for relative, text in resources['source_texts'].items():
            path = knowledge / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode('utf-8'))
            refs.append(dict(path=relative, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        templates = []
        for index in range(count):
            current = copy.deepcopy(design)
            if count > 1:
                current.pop('design_id')
                treatment = current['experiment_plan']['treatments'][0]['feature']
                treatment['horizon'] = 17 + index * 2
                if not shared_baseline:
                    current['feature_plan'] = dict(treatment, horizon=16 + index * 2)
                    current['experiment_plan']['baseline'] = copy.deepcopy(current['feature_plan'])
                current = validate_hypothesis_design(dict(summary='Offline multi-pair fixture.', designs=[current]),
                    resources['evidence_pack'], SemanticPolicy())['designs'][0]
            result = compile_hypothesis_design(current, resources, scope)
            self.assertEqual(result['status'], 'compiled', result)
            attachment = 'raw/research/experiments/' + ('offline-pair.json' if index == 0 else f'offline-pair-{index}.json')
            document = dict(resource_contract_version=2, versions=_design_versions(SemanticPolicy()),
                            compiler_input=dict(design=current, resources=resources, scope=scope),
                            experiment=result['experiment'])
            path = knowledge / attachment
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document), encoding='utf-8')
            refs.append(dict(path=attachment, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            for row in copy.deepcopy(result['drafts']):
                row.update(semantic_status='reviewed', experiment_paths=[attachment])
                templates.append(row)
        (knowledge / 'machine/data_ledger.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in resources['field_rows']), encoding='utf-8')
        (knowledge / 'machine/source_index.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in resources['source_index'].values()), encoding='utf-8')
        receipt = stage_semantic_release(knowledge, dict(resource_contract_version=2, source_refs=refs,
            validated_operators=resources['operator_rows'], validated_templates=templates), '2026-10-16T00:00:00Z')
        publish_semantic_release(knowledge, receipt)
        return knowledge, scope

    def paired_snapshot(self, knowledge, scope, policy=None):
        """Input: vault Path/scope/policy dicts. Output: real opt-in snapshot dict; isolate unrelated readiness artifacts."""
        with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'):
            return stages.create_start_snapshot(knowledge, 'option-1', scope,
                research_policy=dict(paired_scout=True) if policy is None else policy)

    def test_paired_policy_defaults_off_without_changing_legacy_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.make_knowledge(Path(tmp))
            with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'):
                old = stages.create_start_snapshot(knowledge, 'option-1', scope)
                for policy in (None, {}, dict(paired_scout=False)):
                    self.assertEqual(old, stages.create_start_snapshot(knowledge, 'option-1', scope, research_policy=policy))

    def test_paired_policy_requires_strict_bool_and_reviewed_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.make_knowledge(Path(tmp))
            for value in ('true', 'false', 1, 0, None, [], {}):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'paired_scout.*bool'):
                    self.paired_snapshot(knowledge, scope, dict(paired_scout=value))
            with self.assertRaisesRegex(ValueError, 'paired_scout.*immutable|paired_scout.*reviewed'):
                self.paired_snapshot(knowledge, scope)

    def test_paired_freezes_full_sources_release_versions_and_exact_attachments(self):
        from wqb import hypothesis_selection
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.paired_knowledge(Path(tmp))
            snapshot = self.paired_snapshot(knowledge, scope)
            self.assertEqual(snapshot['research_policy'], dict(paired_scout=True))
            self.assertEqual(snapshot['resource_contract_version'], 2)
            context = hypothesis_selection.validate_operational_resource_context(snapshot)
            self.assertEqual(len(context['experiments']), 1)
            self.assertEqual(len(context['experiments'][0]['arms']), 2)
            self.assertEqual(context['versions']['parameter_policy']['owner'], 'project')
            for relative, text in snapshot['operational_resource_context']['source_files'].items():
                self.assertEqual(text.encode('utf-8'), (knowledge / relative).read_bytes())
            frozen = json.loads(json.dumps(snapshot))
            # A running mission never opens the active vault, even after replacement.
            (knowledge / 'raw/research/experiments/offline-pair.json').write_text('{}')
            with patch('pathlib.Path.read_bytes', side_effect=AssertionError('live vault read')):
                self.assertEqual(context, hypothesis_selection.validate_operational_resource_context(frozen))
                stages._snapshot_schedule_inputs(frozen, 'option-1', scope)
            with self.assertRaisesRegex(ValueError, 'digest|bytes'):
                self.paired_snapshot(knowledge, scope)

    def test_paired_rejects_source_mutation_before_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.paired_knowledge(Path(tmp))
            source = next(iter((knowledge / 'raw/platform').rglob('*.md')))
            source.write_bytes(source.read_bytes() + b'\nmutation')
            with self.assertRaisesRegex(ValueError, 'digest|hash|bytes'):
                self.paired_snapshot(knowledge, scope)

    def test_paired_never_enters_unpaired_scout_planner(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.paired_knowledge(Path(tmp))
            snapshot = self.paired_snapshot(knowledge, scope)
            run = Path(tmp) / 'offline-run'
            run.mkdir()
            (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)))
            from wqb.hypothesis_selection import validate_operational_resource_context
            settings = validate_operational_resource_context(snapshot)['experiments'][0]['arms'][0]['settings']
            config = dict(settings, instrument_type=settings['instrumentType'], unit_handling=settings['unitHandling'],
                nan_handling=settings['nanHandling'], max_alphas_per_round=3)
            with patch('wqb.research_planning._hypothesis_pool', side_effect=AssertionError('legacy grid')):
                plan = research_planning.prepare_source_plan(run, config, {}, 'now')
                self.assertEqual(len(plan['scheduled_hypotheses']), 2)

    def replace_paired_attachment(self, knowledge, change):
        """Input: temporary vault Path/mutator callable. Output: None. Restage a separately reviewed fixture release."""
        from wqb.semantic_publication import read_semantic_release, stage_semantic_release, publish_semantic_release
        receipt = read_semantic_release(knowledge)
        templates = [json.loads(line) for line in Path(receipt['paths']['template_library']).read_text().splitlines()]
        operators = [json.loads(line) for line in Path(receipt['paths']['operator_ledger']).read_text().splitlines()]
        attachment = knowledge / 'raw/research/experiments/offline-pair.json'
        document = json.loads(attachment.read_text())
        change(document, templates, operators)
        attachment.write_text(json.dumps(document), encoding='utf-8')
        refs = [dict(path=ref['path'], sha256=hashlib.sha256((knowledge / ref['path']).read_bytes()).hexdigest())
                for ref in receipt['manifest']['source_refs']]
        publish_semantic_release(knowledge, stage_semantic_release(knowledge, dict(resource_contract_version=2,
            source_refs=refs, validated_templates=templates, validated_operators=operators), '2026-10-16T01:00:00Z'))

    def test_paired_rejects_reviewed_but_incompatible_versions_and_rehashed_experiment(self):
        for target in ('context_version', 'resource_rules_digest', 'parameter_policy', 'resource_contract_version',
                       'attachment', 'unreviewed', 'missing_ref', 'missing_source'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                knowledge, scope = self.paired_knowledge(Path(tmp))
                def change(doc, templates, operators):
                    """Input: temporary attachment/resource dicts. Output: None. Mutate one reviewed contract independently."""
                    if target == 'parameter_policy':
                        doc['versions'][target]['maximum'] = 999
                    elif target in ('context_version', 'resource_rules_digest'):
                        doc['versions'][target] = 'incompatible'
                    elif target == 'resource_contract_version':
                        doc[target] = 1
                    elif target == 'attachment':
                        doc['experiment']['arms'][0]['binding']['bound_expression'] = 'outside'
                    elif target == 'unreviewed':
                        templates[0]['semantic_status'] = 'unreviewed'
                    elif target == 'missing_ref':
                        templates[0]['experiment_paths'] = []
                    else:
                        del doc['compiler_input']['resources']['source_texts'][
                            next(iter(doc['compiler_input']['resources']['source_texts']))]
                self.replace_paired_attachment(knowledge, change)
                with self.assertRaises(ValueError):
                    self.paired_snapshot(knowledge, scope)

    def test_paired_readiness_replaces_only_verified_legacy_reader_incompatibility(self):
        from wqb.run_readiness import ReadinessIssue, ReadinessReport
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.paired_knowledge(Path(tmp))
            snapshot = self.paired_snapshot(knowledge, scope)
            legacy_issue = ReadinessIssue(level='block', code='v2_hypothesis_unexecutable',
                message='source-backed resource contract requires approved operational evidence context')
            for extra in ([], [ReadinessIssue(level='block', code='stale_source', message='stale')]):
                report = ReadinessReport('research', 'now', False, True, [legacy_issue, *extra])
                with patch('wqb.workflow_stage_adapters.evaluate_run_readiness', return_value=report):
                    if extra:
                        with self.assertRaisesRegex(ValueError, 'stale_source'):
                            stages._require_start_snapshot_readiness(knowledge, scope, operational_snapshot=snapshot)
                    else:
                        stages._require_start_snapshot_readiness(knowledge, scope, operational_snapshot=snapshot)
                    with self.assertRaisesRegex(ValueError, 'v2_hypothesis_unexecutable'):
                        stages._require_start_snapshot_readiness(knowledge, scope)
            with patch('wqb.workflow_stage_adapters.evaluate_run_readiness',
                       return_value=ReadinessReport('research', 'now', False, True, [])):
                with self.assertRaisesRegex(ValueError, 'blocked'):
                    stages._require_start_snapshot_readiness(knowledge, scope, operational_snapshot=snapshot)

    def test_paired_rejects_before_mission_creation_with_specific_readiness_error(self):
        from wqb.orchestrator import WorkflowOrchestrator, OrchestratorPaths
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge, scope = self.make_knowledge(root)
            controller = WorkflowOrchestrator(OrchestratorPaths(root, root, knowledge, root / 'runs'))
            with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'):
                with self.assertRaisesRegex(ValueError, 'paired_scout.*immutable'):
                    controller.start('offline', 'option-1', '2026-10-16T00:00:00Z',
                                     selected_scope=scope, research_policy=dict(paired_scout=True))
            self.assertFalse(list((root / 'runs').glob('*/run_manifest.json')))

    def test_raw_catalog_metadata_survives_real_compile_load_and_snapshot(self):
        from wqb.data_ledger_compile import compile_data_ledger_from_raw
        from wqb.data_ledger import load_data_ledger, data_ledger_record_to_dict
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.make_knowledge(Path(tmp))
            capture = knowledge / 'raw/platform/data_fields/2026-10-13'
            capture.mkdir(parents=True)
            exact_scope = dict(instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000')
            fields = selection_fixture()['data_ledger_rows']
            raw = [dict(scope=exact_scope, data_set=dict(id=row['dataset_id'], category='fundamental'),
                field=dict(id=row['field_id'], type=row['field_type'], coverage=1, description=row['field_description'],
                           units=row['units'], available_at=row['available_at'], vector_grain='company_event')) for row in fields]
            (capture / 'data_fields.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in raw))
            (capture / 'scopes.jsonl').write_text(json.dumps(dict(scope=exact_scope, status='completed', certification_status='complete')) + '\n')
            (capture / 'manifest.json').write_text(json.dumps(dict(generated_at='2026-10-13T00:00:00Z',
                certification_status='complete', requested_matrix=[exact_scope])))
            compile_data_ledger_from_raw(knowledge, capture_dir=capture, generated_at='2026-10-14T00:00:00Z')
            records = load_data_ledger(knowledge / 'machine/data_ledger.jsonl')
            self.assertEqual({row.units for row in records}, {'USD'})
            self.assertTrue(all(data_ledger_record_to_dict(row)['available_at'] == fields[0]['available_at'] for row in records))
            with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'):
                snapshot = stages.create_start_snapshot(knowledge, 'option-1', scope)
            self.assertEqual({row['field_id'] for row in snapshot['data_ledger_rows']}, {'cash', 'debt'})
            self.assertTrue(all(row['vector_grain'] == 'company_event' for row in snapshot['data_ledger_rows']))
            del raw[1]['field']['available_at']
            (capture / 'data_fields.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in raw))
            compile_data_ledger_from_raw(knowledge, capture_dir=capture, generated_at='2026-10-14T01:00:00Z')
            records = load_data_ledger(knowledge / 'machine/data_ledger.jsonl')
            self.assertIsNone(next(row for row in records if row.field_id == 'debt').available_at)
            with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'):
                with self.assertRaisesRegex(ValueError, 'executable'):
                    stages.create_start_snapshot(knowledge, 'option-1', scope)

    def test_partial_executable_snapshot_retains_bounded_rejection_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.make_knowledge(Path(tmp))
            path = knowledge / 'machine/template_library.jsonl'
            valid = json.loads(path.read_text().splitlines()[0])
            invalid = copy.deepcopy(valid)
            invalid.update(template_id='invalid', hypothesis_id='invalid')
            invalid['input_slots'][0]['required_metadata'].append('missing_fact')
            path.write_text(''.join(json.dumps(row) + '\n' for row in [valid, invalid]))
            with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'):
                snapshot = stages.create_start_snapshot(knowledge, 'option-1', scope)
            reports = snapshot['gate_metadata']['hypothesis_quality']
            self.assertEqual(reports['template_pass_count'], 1)
            self.assertEqual(reports['template_attempt_count'], 2)
            self.assertTrue(reports['rejections'])
            self.assertIn('reason_id', reports['rejections'][0])

    def test_replay_keeps_frozen_as_of_and_rejects_changed_as_of(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.make_knowledge(Path(tmp))
            with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'):
                snapshot = stages.create_start_snapshot(knowledge, 'option-1', scope)
            _, replay_scope, *_ = stages._snapshot_schedule_inputs(snapshot, 'option-1', scope)
            self.assertEqual(replay_scope['as_of'], scope['as_of'])
            with self.assertRaisesRegex(ValueError, 'as_of|scope'):
                stages._snapshot_schedule_inputs(snapshot, 'option-1', dict(scope, as_of='2099-01-01T00:00:00Z'))

    def test_mixed_vault_invalid_v2_does_not_silently_fallback_to_legacy(self):
        from wqb.run_readiness import _validate_scope_artifacts
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.make_knowledge(Path(tmp))
            template_path = knowledge / 'machine/template_library.jsonl'
            templates = [json.loads(line) for line in template_path.read_text().splitlines()]
            legacy = dict(template_id='legacy', skeleton='rank({field})', hypothesis='Legacy signal.',
                          required_field_types=['MATRIX'], compatible_semantic_tags=[], status='seed')
            template_path.write_text(''.join(json.dumps(row) + '\n' for row in [legacy, *templates]))
            data_path = knowledge / 'machine/data_ledger.jsonl'
            rows = [json.loads(line) for line in data_path.read_text().splitlines()]
            del rows[1]['units']
            for row in rows:
                row['compatible_template_ids'] = ['legacy']
            data_path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            issues = []
            _validate_scope_artifacts(knowledge, 'plan-only', issues, 'USA', 'TOP3000', 1,
                                       __import__('datetime').date(2026, 10, 14), None)
            self.assertIn('v2_hypothesis_unexecutable', [issue.code for issue in issues])
            with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'):
                with self.assertRaisesRegex(ValueError, 'executable|binding'):
                    stages.create_start_snapshot(knowledge, 'option-1', scope)

    def make_knowledge(self, root):
        """Input: root Path. Output: knowledge Path and binding scope dict. Write explicitly offline raw metadata."""
        snapshot = selection_fixture()
        write_start_artifacts(root, snapshot['data_ledger_rows'])
        knowledge = root / 'knowledge'
        (knowledge / 'machine/template_library.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in snapshot['template_rows']), encoding='utf-8')
        (knowledge / 'machine/operator_ledger.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in snapshot['operator_rows']), encoding='utf-8')
        # Neither slot needs legacy compatible_template_ids for v2 dependency capture.
        fields = snapshot['data_ledger_rows']
        for row in fields:
            row.update(coverage=1, source_quality='platform_raw_capture', coverage_status='measured_raw',
                       source_updated_at='2026-10-13', compatible_template_ids=[])
        (knowledge / 'machine/data_ledger.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in fields), encoding='utf-8')
        return knowledge, snapshot['selected_scope']

    def test_freezes_complete_raw_slots_and_paired_release_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.make_knowledge(Path(tmp))
            with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'):
                snapshot = stages.create_start_snapshot(knowledge, 'option-1', scope)
            self.assertEqual(snapshot.get('hypothesis_binding_version'), 2)
            self.assertEqual({row['field_id'] for row in snapshot['data_ledger_rows']}, {'cash', 'debt'})
            self.assertEqual(snapshot['data_ledger_rows'][0]['units'], 'USD')
            self.assertIn('available_at', snapshot['data_ledger_rows'][0])
            self.assertTrue(snapshot['operator_rows'])
            receipt = snapshot['semantic_release']
            for name, digest in receipt['digests'].items():
                self.assertEqual(hashlib.sha256(Path(receipt['paths'][name]).read_bytes()).hexdigest(), digest)

    def test_row_limit_never_truncates_a_required_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.make_knowledge(Path(tmp))
            with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'), patch(
                    'wqb.workflow_stage_adapters.START_SNAPSHOT_DATA_LEDGER_ROW_LIMIT', 1):
                with self.assertRaisesRegex(ValueError, 'binding|dependencies|executable'):
                    stages.create_start_snapshot(knowledge, 'option-1', scope)

    def test_unknown_availability_is_not_replaced_by_capture_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.make_knowledge(Path(tmp))
            path = knowledge / 'machine/data_ledger.jsonl'
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            del rows[1]['available_at']
            path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'):
                with self.assertRaisesRegex(ValueError, 'binding|executable'):
                    stages.create_start_snapshot(knowledge, 'option-1', scope)

    def test_consumed_bytes_are_verified_before_decode(self):
        from wqb.semantic_publication import read_semantic_release
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.make_knowledge(Path(tmp))
            def stale_receipt(root):
                """Input: root Path. Output: stale real receipt dict. Emulate legacy bytes changing after selection."""
                receipt = read_semantic_release(root)
                Path(receipt['paths']['template_library']).write_bytes(b'not JSON')
                return receipt
            with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'), patch(
                    'wqb.semantic_publication.read_semantic_release', side_effect=stale_receipt):
                with self.assertRaisesRegex(ValueError, 'digest|bytes'):
                    stages.create_start_snapshot(knowledge, 'option-1', scope)

    def test_receipt_revalidated_after_pair_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = self.make_knowledge(Path(tmp))
            with patch('wqb.workflow_stage_adapters._require_start_snapshot_readiness'), patch(
                    'wqb.semantic_publication.validate_semantic_receipt', side_effect=ValueError('invalidated pair')):
                with self.assertRaisesRegex(ValueError, 'invalidated pair'):
                    stages.create_start_snapshot(knowledge, 'option-1', scope)


if __name__ == '__main__':
    unittest.main()
