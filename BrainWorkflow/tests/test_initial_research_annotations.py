"""Offline annotations contract; all raw, manifests and model replies are fixtures."""

from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch

from tests import test_initial_research_planning as fixtures
from tests import test_initial_model_worker as workers
from wqb import initial_research_planning as planning


def enable(fixture):
    """Input: isolated planning fixture. Output: None; opt into frozen package policy."""
    fixture.manifest['start_snapshot']['research_policy'].update(
        preplanned_tree_version=1, execution_package_version=1)
    fixture.manifest['start_snapshot']['repair_search_policy'] = dict(schema_version=1, rules=[], traits={})
    fixture.save_manifest()
    fixture.answer['data_characteristics'] = [dict(dataset_id='fictional', field_id='pulse_field',
        known_trait_keys=['units'], unknown_trait_keys=['vector_grain'],
        hypotheses=[dict(trait_key='sampling_frequency_sessions', hypothesis='Cadence may be daily.')],
        suggested_repair_rule_ids=[])]


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        """Input: test instance. Output: None; private certified fixture only."""
        self.f = fixtures.InitialResearchPlanningTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        enable(self.f)

    def test_interrupted_before_seal_recovers_without_runtime_bypass(self):
        from wqb import execution_package
        from wqb.exploration_eligibility import validate_operational_exploration
        fake = fixtures.FakeRunner(return_value=self.f.answer)
        with patch.object(execution_package, 'seal_execution_context', side_effect=RuntimeError('interrupted')):
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                self.f.prepare(fake)
        self.assertTrue((self.f.run / execution_package.TREE_PATH).exists())
        self.assertFalse((self.f.run / execution_package.SEAL_PATH).exists())
        self.assertEqual(planning._read(self.f.run / planning.TASK_PATH)['status'], 'outcome_received')
        snapshot = planning._read(self.f.run / 'run_manifest.json')['start_snapshot']
        with self.assertRaises(ValueError):
            validate_operational_exploration(self.f.run, self.f.knowledge, snapshot)
        result = self.f.prepare(fake)
        self.assertEqual(result['status'], 'completed', result)
        self.assertTrue((self.f.run / execution_package.SEAL_PATH).exists())
        validate_operational_exploration(self.f.run, self.f.knowledge, snapshot)
        self.assertEqual(fake.call_count, 1)

    def test_completed_replay_uses_sealed_package_without_global_vault(self):
        fake = fixtures.FakeRunner(return_value=self.f.answer)
        result = self.f.prepare(fake)
        self.assertEqual(result['status'], 'completed', result)
        self.f.knowledge.rename(self.f.root / 'unavailable_knowledge')
        with patch.object(planning, 'certify_exploration_resources', side_effect=AssertionError('global IO')):
            self.assertEqual(self.f.prepare(fake), result)
        self.assertEqual(fake.call_count, 1)
        self.f.resources['settings']['decay'] += 1
        self.assertEqual(self.f.prepare(fake)['status'], 'blocked')
        self.f.resources['settings']['decay'] -= 1
        self.assertEqual(self.f.prepare(fake), result)
        (self.f.run / planning.DATA_CHARACTERISTICS_PATH).write_text('{}')
        self.assertEqual(self.f.prepare(fake)['status'], 'blocked')
        self.assertEqual(fake.call_count, 1)

    def test_interrupted_unsealed_retry_still_requires_original_raw(self):
        from wqb import execution_package
        fake = fixtures.FakeRunner(return_value=self.f.answer)
        with patch.object(execution_package, 'seal_execution_context', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):
                self.f.prepare(fake)
        raw = self.f.knowledge / next(iter(self.f.resources['source_texts']))
        raw.write_text('tampered', encoding='utf-8')
        result = self.f.prepare(fake)
        self.assertEqual(result['status'], 'blocked', result)
        self.assertFalse((self.f.run / execution_package.SEAL_PATH).exists())
        self.assertEqual(fake.call_count, 1)

    def test_completed_missing_seal_never_recaptures_global_resources(self):
        from wqb import execution_package
        fake = fixtures.FakeRunner(return_value=self.f.answer)
        result = self.f.prepare(fake)
        self.assertEqual(result['status'], 'completed', result)
        seal = self.f.run / execution_package.SEAL_PATH
        seal.rename(seal.with_suffix('.unavailable'))
        task = planning._read(self.f.run / planning.TASK_PATH)
        with patch.object(planning, 'certify_exploration_resources', side_effect=AssertionError('global IO')):
            self.assertEqual(self.f.prepare(fake)['status'], 'blocked')
        self.assertEqual(planning._read(self.f.run / planning.TASK_PATH), task)
        self.assertFalse(seal.exists())
        self.assertEqual(fake.call_count, 1)

    def test_interrupted_after_seal_finishes_without_global_vault(self):
        from wqb import research_tree
        original = research_tree.freeze_tree
        def freeze(*args):
            """Input: producer freeze args. Output: none; simulate interruption after authentic sealing."""
            original(*args)
            raise RuntimeError('after seal')
        fake = fixtures.FakeRunner(return_value=self.f.answer)
        with patch.object(research_tree, 'freeze_tree', side_effect=freeze):
            with self.assertRaisesRegex(RuntimeError, 'after seal'):
                self.f.prepare(fake)
        self.assertEqual(planning._read(self.f.run / planning.TASK_PATH)['status'], 'outcome_received')
        self.f.knowledge.rename(self.f.root / 'unavailable_knowledge')
        with patch.object(planning, 'certify_exploration_resources', side_effect=AssertionError('global IO')):
            result = self.f.prepare(fake)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result, self.f.prepare(fake))
        self.assertEqual(fake.call_count, 1)

    def test_sealed_replay_rejects_changed_policy_and_library(self):
        fake = fixtures.FakeRunner(return_value=self.f.answer)
        result = self.f.prepare(fake)
        self.assertEqual(result['status'], 'completed', result)
        self.f.knowledge.rename(self.f.root / 'unavailable_knowledge')
        self.f.policy['plan_depth'] += 1
        self.assertEqual(self.f.prepare(fake)['status'], 'blocked')
        self.f.policy['plan_depth'] -= 1
        self.assertEqual(self.f.prepare(fake, receipts=[{}])['status'], 'blocked')
        self.assertEqual(self.f.prepare(fake), result)
        self.assertEqual(fake.call_count, 1)

    def test_sealed_replay_rejects_rehashed_task_drift(self):
        fake = fixtures.FakeRunner(return_value=self.f.answer)
        result = self.f.prepare(fake)
        self.assertEqual(result['status'], 'completed', result)
        self.f.knowledge.rename(self.f.root / 'unavailable_knowledge')
        path = self.f.run / planning.TASK_PATH
        saved = planning._read(path)
        mutations = [lambda t: t['brief'].update(composition_contract='tampered'),
            lambda t: t['answer']['data_characteristics'][0]['hypotheses'][0].update(hypothesis='tampered'),
            lambda t: t['result'].update(knowledge_status='reviewed'),
            lambda t: t.pop('result')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed = deepcopy(saved)
                mutation(changed)
                planning._save_task(path, changed)
                self.assertEqual(self.f.prepare(fake)['status'], 'blocked')
                self.assertEqual(planning._read(path), changed)
        planning._save_task(path, saved)
        self.assertEqual(self.f.prepare(fake), result)
        self.assertEqual(fake.call_count, 1)

    def test_materializes_before_freeze_and_replays_once(self):
        from wqb import research_tree
        original = research_tree.freeze_tree
        captured = []
        def freeze(*args):
            """Input: freeze arguments. Output: frozen tree after checking annotation ordering."""
            captured.append(json.loads((self.f.run / planning.DATA_CHARACTERISTICS_PATH).read_text()))
            return original(*args)
        fake = fixtures.FakeRunner(return_value=self.f.answer)
        with patch.object(research_tree, 'freeze_tree', side_effect=freeze):
            result = self.f.prepare(fake)
        self.assertEqual(result['status'], 'completed', result)
        artifact = captured[0]
        row = artifact['fields'][0]
        self.assertEqual(row['known_facts']['units']['value'], 'score')
        self.assertTrue(row['known_facts']['units']['evidence_refs'])
        self.assertIn('vector_grain', row['unknown_trait_keys'])
        self.assertNotIn('sampling_frequency_sessions', row['known_facts'])
        self.assertEqual(row['hypotheses'], self.f.answer['data_characteristics'][0]['hypotheses'])
        path = self.f.run / planning.DATA_CHARACTERISTICS_PATH
        self.assertEqual(result['data_characteristics_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(result, self.f.prepare(fake))
        self.assertEqual(fake.call_count, 1)
        path.write_text('{}')
        self.assertEqual(self.f.prepare(fake)['status'], 'blocked')
        self.assertEqual(fake.call_count, 1)

    def test_invalid_annotations_are_durable_blockers(self):
        mutations = [lambda a: a.pop('data_characteristics'),
            lambda a: a['data_characteristics'].clear(),
            lambda a: a['data_characteristics'].append(deepcopy(a['data_characteristics'][0])),
            lambda a: a['data_characteristics'][0].update(field_id='unused'),
            lambda a: a['data_characteristics'][0].update(known_trait_keys=['invented']),
            lambda a: a['data_characteristics'][0].update(known_trait_keys=['vector_grain']),
            lambda a: a['data_characteristics'][0].update(unknown_trait_keys=['units']),
            lambda a: a['data_characteristics'][0].update(suggested_repair_rule_ids=['invented']),
            lambda a: a['data_characteristics'][0].update(units='invented'),
            lambda a: a['data_characteristics'][0]['hypotheses'][0].update(hypothesis='x' * 2000)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                other = fixtures.InitialResearchPlanningTests()
                other.setUp()
                try:
                    enable(other)
                    mutation(other.answer)
                    fake = fixtures.FakeRunner(return_value=other.answer)
                    self.assertEqual(other.prepare(fake)['status'], 'blocked')
                    self.assertEqual(other.prepare(fake)['status'], 'blocked')
                    self.assertEqual(fake.call_count, 1)
                    self.assertFalse((other.run / 'runtime/experiment_tree.json').exists())
                finally:
                    other.doCleanups()

    def test_new_policy_requires_exact_versions_and_frozen_repair(self):
        fake = fixtures.FakeRunner(return_value=self.f.answer)
        policy = self.f.manifest['start_snapshot']['research_policy']
        for value in (True, '1', 2, None):
            policy['preplanned_tree_version'] = value
            self.f.save_manifest()
            self.assertEqual(self.f.prepare(fake)['status'], 'blocked')
        policy['preplanned_tree_version'] = 1
        self.f.manifest['start_snapshot'].pop('repair_search_policy')
        self.f.save_manifest()
        self.assertEqual(self.f.prepare(fake)['status'], 'blocked')
        fake.assert_not_called()

    def test_old_schema_and_brief_are_unchanged(self):
        policy = self.f.manifest['start_snapshot']['research_policy']
        policy.pop('execution_package_version')
        policy.pop('preplanned_tree_version')
        self.f.save_manifest()
        self.f.answer.pop('data_characteristics')
        result = self.f.prepare(fixtures.FakeRunner(return_value=self.f.answer))
        self.assertEqual(result['status'], 'completed', result)
        task = planning._read(self.f.run / planning.TASK_PATH)
        self.assertEqual(task['brief']['output_schema'], planning._output_schema(1))
        self.assertNotIn('annotation_context', task['brief'])
        self.assertNotIn('data_characteristics_sha256', result)

    def test_existing_repair_hints_are_resolved_without_policy_mutation(self):
        from tests.test_repair_search import search_fixture
        _, policy = search_fixture()
        self.f.manifest['start_snapshot']['repair_search_policy'] = deepcopy(policy)
        self.f.save_manifest()
        self.f.answer['data_characteristics'][0]['suggested_repair_rule_ids'] = ['smooth']
        before = deepcopy(self.f.resources)
        result = self.f.prepare(fixtures.FakeRunner(return_value=self.f.answer))
        self.assertEqual(result['status'], 'completed', result)
        artifact = planning._read(self.f.run / planning.DATA_CHARACTERISTICS_PATH)
        hint = artifact['fields'][0]['repair_resource_hints'][0]
        self.assertEqual(hint['rule_id'], 'smooth')
        self.assertEqual(hint['edit'], 'decay')
        self.assertEqual(hint['purpose'], 'documentation_only')
        self.assertEqual(self.f.resources, before)
        self.assertEqual(planning._read(self.f.run / 'run_manifest.json')['start_snapshot'][
            'repair_search_policy'], policy)

    def test_new_mode_never_reuses_old_model_outcome(self):
        original = fixtures.InitialResearchPlanningTests()
        original.setUp()
        self.addCleanup(original.doCleanups)
        fake = fixtures.FakeRunner(return_value=original.answer)
        self.assertEqual(original.prepare(fake)['status'], 'completed')
        old_task = planning._read(original.run / planning.TASK_PATH)
        enable(original)
        self.assertEqual(original.prepare(fake)['status'], 'blocked')
        self.assertEqual(fake.call_count, 1)
        old_brief = old_task['brief']
        new_brief = planning._brief(original.resources, original.manifest,
            old_task['certificate'], [], original.policy)
        self.assertNotEqual(planning._digest(old_brief), planning._digest(new_brief))

    def test_catalog_field_not_used_requires_no_annotation(self):
        # Pure validation ensures extra catalog identities cannot acquire annotations.
        context = dict(fields=[dict(dataset_id='fictional', field_id='pulse_field',
            known_facts={'units': dict(value='score')}, unknown_trait_keys=['vector_grain']),
            dict(dataset_id='fictional', field_id='unused', known_facts={}, unknown_trait_keys=[])],
            repair_rule_ids=[])
        used = {('fictional', 'pulse_field')}
        self.assertEqual(len(planning._annotation_fields(self.f.answer, dict(annotation_context=context), used)), 1)
        answer = deepcopy(self.f.answer)
        answer['data_characteristics'][0]['field_id'] = 'unused'
        with self.assertRaises(ValueError):
            planning._annotation_fields(answer, dict(annotation_context=context), used)

    def test_unverified_ledger_trait_never_becomes_raw_fact(self):
        resources = deepcopy(self.f.resources)
        resources['field_rows'][0]['sampling_frequency_sessions'] = 999
        context = planning._annotation_context(resources, self.f.manifest)
        self.assertNotIn('sampling_frequency_sessions', context['fields'][0]['known_facts'])
        self.assertIn('sampling_frequency_sessions', context['fields'][0]['unknown_trait_keys'])


class AnnotationWorkerTests(unittest.TestCase):
    def worker(self):
        """Input: test instance. Output: authenticated new-mode offline worker fixture."""
        fixture = workers.InitialModelWorkerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        enable(fixture.fixture)
        from wqb.exploration_eligibility import certify_exploration_resources
        certificate = certify_exploration_resources(fixture.run, fixture.fixture.knowledge,
            fixture.fixture.resources, fixture.fixture.scope)
        fixture.task.update(manifest=deepcopy(fixture.fixture.manifest), certificate=certificate,
            brief=planning._brief(fixture.fixture.resources, fixture.fixture.manifest,
                certificate, [], fixture.fixture.policy))
        fixture.save_task()
        fixture.answer = deepcopy(fixture.fixture.answer)
        return fixture

    def test_readonly_worker_preserves_fourth_field(self):
        fixture = self.worker()
        self.assertEqual(fixture.execute(), fixture.answer)

    def test_worker_rejects_unknown_rule_reference(self):
        fixture = self.worker()
        fixture.answer['data_characteristics'][0]['suggested_repair_rule_ids'] = ['invented']
        with self.assertRaisesRegex(ValueError, 'invalid annotation reference'):
            fixture.execute()

    def test_worker_rejects_rehashed_compilation_settings(self):
        from wqb.initial_model_worker import initial_model_projection
        fixture = self.worker()
        fixture.task['brief']['annotation_context']['compilation_settings']['decay'] = 999
        fixture.save_task()
        with self.assertRaisesRegex(ValueError, 'compilation resources changed'):
            initial_model_projection(fixture.run)
