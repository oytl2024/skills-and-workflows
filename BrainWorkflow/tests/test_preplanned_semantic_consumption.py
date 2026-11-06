"""Canonical explanation consumption uses temporary certified captures, never live APIs."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from wqb import preplanned_start as start
from wqb.config import DEFAULT_CONFIG
from wqb.semantic_contracts import CARD_FIELDS


class PreplannedSemanticConsumptionTests(unittest.TestCase):
    def setUp(self):
        """Input: none. Output: certified field/selected immutable explanation fixture with cleanup."""
        from tests.test_field_semantic_enrichment import FieldSemanticEnrichmentTests
        self.fixture = FieldSemanticEnrichmentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.scope = dict(self.fixture.raw['scope'], as_of='2026-10-30T00:00:00Z')
        self.card = dict(hypothesis_card={key: 'A falsifiable economic assumption' for key in CARD_FIELDS},
                         evidence_refs=[dict(self.fixture.evidence, kind='hypothesis')])
        self.fixture.target['hypothesis_cards'] = [self.card]
        self.fixture.attach()
        self.fixture.ledger.write_text(json.dumps(self.fixture.row), encoding='utf-8')

    def test_canonical_fallback_consumes_verified_explanation_without_jobs_or_writes(self):
        """Input: canonical field selector without design jobs. Output: one source-bound resource with hypothesis context."""
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        resources, receipts, gaps = start._local_resources(self.root, self.scope, DEFAULT_CONFIG, 1)
        self.assertEqual(len(resources), 1, gaps)
        histories = resources[0]['evidence_pack']['histories']
        self.assertEqual(len(histories), 1)
        for name in CARD_FIELDS:
            self.assertIn(name + ':', histories[0]['statement'])
        self.assertTrue(all(ref['kind'] == 'hypothesis' for ref in histories[0]['evidence_refs']))
        self.assertEqual(resources[0]['field_rows'][0]['field_semantics_ref'], self.fixture.row['field_semantics_ref'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_invalid_selected_reference_blocks_dataset_instead_of_silent_fallback(self):
        """Input: forged canonical explanation hash. Output: no resource and explicit semantic-source rejection."""
        row = deepcopy(self.fixture.row)
        row['field_semantics_ref']['sha256'] = '0' * 64
        self.fixture.ledger.write_text(json.dumps(row), encoding='utf-8')
        resources, _, gaps = start._local_resources(self.root, self.scope, DEFAULT_CONFIG, 1)
        self.assertEqual(resources, [])
        self.assertTrue(any('field explanation' in g['reason'] for g in gaps), gaps)

    def test_valid_punctuated_card_has_sentence_compatible_bounded_history(self):
        """Input: seven valid punctuated card sections. Output: readable one-sentence projection without changing the selected card."""
        from wqb.knowledge_compile import resolve_field_semantics
        from wqb.semantic_contracts import hypothesis_card_from_dict
        endings = ['\u3002', '.', '\uff01', '\uff1f', '!', '?', '\u3002']
        for key, ending in zip(CARD_FIELDS, endings):
            self.card['hypothesis_card'][key] += ending
        self.fixture.attach()
        self.fixture.ledger.write_text(json.dumps(self.fixture.row), encoding='utf-8')
        selected = resolve_field_semantics(self.root, self.fixture.row)
        self.assertEqual(selected['status'], 'supported')
        before = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        resources, _, gaps = start._local_resources(self.root, self.scope, DEFAULT_CONFIG, 1)
        self.assertEqual(len(resources), 1, gaps)
        history = resources[0]['evidence_pack']['histories'][0]
        hypothesis_card_from_dict(dict.fromkeys(CARD_FIELDS, history['statement']))
        for key in CARD_FIELDS:
            self.assertIn(key + ':', history['statement'])
        self.assertEqual(history['evidence_refs'], self.card['evidence_refs'])
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()})

    def test_unrelated_explanation_jobs_do_not_exhaust_design_recovery_bound(self):
        """Input: many unrelated prepared job manifests. Output: canonical field selection still available."""
        for number in range(start.MAX_LOCAL_JOBS + 1):
            path = self.root / 'machine/semantic_jobs' / ('unrelated-' + str(number)) / 'run_manifest.json'
            path.parent.mkdir(parents=True)
            path.write_text('{"kind":"full_semantic_explanation"}', encoding='utf-8')
        resources, _, gaps = start._local_resources(self.root, self.scope, DEFAULT_CONFIG, 1)
        self.assertEqual(len(resources), 1, gaps)

    def test_129_real_eur_proposal_jobs_do_not_count_against_usa_resource_cap(self):
        """Input: 129 real EUR proposal-only jobs/USA canonical fixture. Output: USA resources without cap failure."""
        from wqb.semantic_compilation import prepare_design_job, verify_design_materials
        from wqb.semantic_contracts import SemanticPolicy
        jobs = []
        for number in range(129):
            pack = dict(scope=dict(self.scope, region='EUR'),
                source_index={self.fixture.source['path']: deepcopy(self.fixture.source)},
                source_texts={self.fixture.source['path']: (self.root / self.fixture.source['path']).read_text(encoding='utf-8')},
                allowed_role_semantics=['Cash balance', 'proposal-' + str(number)],
                allowed_operator_intents=['level'], histories=[])
            job = prepare_design_job(self.root, pack, SemanticPolicy())
            manifest = json.loads((job / 'run_manifest.json').read_text(encoding='utf-8'))
            verified, resource = verify_design_materials(job, manifest, SemanticPolicy(), check_sources=True)
            self.assertEqual(verified['scope']['region'], 'EUR')
            self.assertIsNone(resource)
            jobs.append(job)
        self.assertEqual(len(set(jobs)), 129)
        self.assertEqual(start.MAX_LOCAL_JOBS, 128)
        resources, _, gaps = start._local_resources(self.root, self.scope, DEFAULT_CONFIG, 1)
        self.assertEqual(len(resources), 1, gaps)
        self.assertEqual(resources[0]['evidence_pack']['scope'], self.scope)

    def test_129_bound_usa_jobs_still_exceed_relevant_resource_cap(self):
        """Input: 129 genuine bound USA design jobs. Output: unchanged 128-job maintenance cap."""
        from wqb.semantic_compilation import prepare_design_job
        from wqb.semantic_contracts import SemanticPolicy
        resources, _, gaps = start._local_resources(self.root, self.scope, DEFAULT_CONFIG, 1)
        self.assertEqual(len(resources), 1, gaps)
        jobs = []
        for number in range(129):
            resource = deepcopy(resources[0])
            resource['evidence_pack']['allowed_role_semantics'].append('bound-' + str(number))
            jobs.append(prepare_design_job(self.root, resource['evidence_pack'], SemanticPolicy(), resource))
        self.assertEqual(len(set(jobs)), 129)
        with self.assertRaisesRegex(ValueError, 'lookup exceeds bounded local index'):
            start._local_resources(self.root, self.scope, DEFAULT_CONFIG, 1)

    def test_real_start_composition_delivers_new_hypothesis_context_to_initial_worker(self):
        """Input: canonical explanation and fake initial worker. Output: actual frozen brief contains selected hypotheses."""
        from tests.test_workflow_stage_adapters import valid_option
        from wqb.benchmark_rules import default_benchmark_rules, write_benchmark_rules_jsonl, benchmark_rules_path_for_knowledge
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        paths = SimpleNamespace(knowledge_root=self.root, run_root=Path(temporary.name),
                                project_root=Path(temporary.name), workflow_root=Path(temporary.name))
        write_benchmark_rules_jsonl(benchmark_rules_path_for_knowledge(self.root), default_benchmark_rules())
        config = dict(DEFAULT_CONFIG, selected_scope=self.scope, parallel_workflows=1,
                      initial_hypotheses=1, plan_depth=1,
                      measurement_period=dict(start='2020-01-01', end='2025-01-01'))
        calls = []
        def worker(brief):
            """Input: real initial brief dict. Output: deliberate test-only interruption after observing frozen context."""
            calls.append(deepcopy(brief))
            raise RuntimeError('fixture-observed-context')
        option = valid_option(option_id='semantic-consumption', candidate_scope='USA D1 TOP3000')
        result = start.prepare_preplanned_start(paths, option,
            dict(enable_live_api=False, max_runtime_seconds=3600, max_recoveries=3), config, model_runner=worker)
        self.assertEqual(len(calls), 1, result)
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('mechanism:', calls[0]['evidence_pack']['histories'][0]['statement'])
        self.assertEqual(calls[0]['data_traits'][0]['field_semantics_ref'], self.fixture.row['field_semantics_ref'])


if __name__ == '__main__':
    unittest.main()
