"""Focused offline DIRECT admission and technical rejection tests."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_hypothesis_design import compiler_fixture
from wqb.config import DEFAULT_CONFIG


class DirectKnowledgeTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: isolated current KB without compile jobs or reports."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.design, self.resource, self.scope = compiler_fixture(treatment=True)
        machine = self.root / 'machine'
        machine.mkdir()
        for path, text in self.resource['source_texts'].items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8', newline='\n')
        for row in self.resource['field_rows']:
            row.update(coverage=None, coverage_status='unknown', source_updated_at='2001-01-01',
                       field_description='', semantic_tags=[])
            row.pop('available_at', None)
        for source in self.resource['source_index'].values():
            source['captured_at'] = '2001-01-01T00:00:00Z'
        for operator in self.resource['operator_rows']:
            for ref in operator['definition']['evidence_refs']:
                ref['capture_date'] = '2001-01-01'
        for name, rows in [('source_index', self.resource['source_index'].values()),
                           ('data_ledger', self.resource['field_rows']),
                           ('operator_ledger', self.resource['operator_rows'])]:
            (machine / (name + '.jsonl')).write_text(
                ''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

    def read_resources(self):
        """Input: fixture. Output: DIRECT compiler resources from current machine files."""
        from wqb.research_resource_catalog import read_catalog_resources
        resources, warnings = read_catalog_resources(self.root, self.scope, 1,
            settings=self.resource['settings'], direct_knowledge_version=1)
        self.assertTrue(warnings)
        self.assertEqual(len(resources), 1)
        return resources[0]

    def test_unknown_coverage_semantics_and_old_date_are_exposed(self):
        resource = self.read_resources()
        self.assertEqual(resource['resource_admission_policy'], 'direct_knowledge_v1')
        self.assertIsNone(resource['field_rows'][0]['coverage'])
        self.assertEqual(resource['field_rows'][0]['source_updated_at'], '2001-01-01')
        self.assertFalse((self.root / 'machine/semantic_jobs').exists())

    def normalized(self, resource):
        """Input: DIRECT resource dict. Output: strict normalized typed design dict."""
        from wqb.hypothesis_design import validate_hypothesis_design
        from wqb.semantic_contracts import SemanticPolicy
        answer = deepcopy(self.design)
        path, source = next(iter(resource['source_index'].items()))
        answer['trigger_id'] = path
        answer['evidence_refs'] = [dict(source_path=path, sha256=source['content_hash'],
            capture_date=source['captured_at'][:10], kind='hypothesis', experiment_refs=[])]
        for role in answer['field_roles']:
            row = resource['field_rows'][0]
            role['required_semantics'] = ['field:' + row['dataset_id'] + '/' + row['field_id']]
            role['required_metadata'] = []
        answer.pop('design_id', None)
        return validate_hypothesis_design(dict(summary='Offline direct proposal.', designs=[answer]),
            resource['evidence_pack'], SemanticPolicy())['designs'][0]

    def test_typed_proposal_compiles_without_semantic_proof(self):
        from wqb.exploration_eligibility import validate_exploration
        resource = self.read_resources()
        receipt = validate_exploration(self.normalized(resource), resource, self.scope)
        self.assertEqual(receipt['compiled']['status'], 'compiled')

    def test_direct_keeps_default_finite_repair_without_coverage_certification(self):
        from wqb.preplanned_start import _repair_policy
        from wqb.repair_search import _validate_v2_sources
        resource = self.read_resources()
        policy = _repair_policy(resource)
        self.assertEqual(policy['schema_version'], 2)
        self.assertTrue(policy['rules'])
        self.assertEqual({rule['edit'] for rule in policy['rules']}, {'decay', 'truncation'})
        _validate_v2_sources(policy['resources'])
        self.assertIsNone(policy['resources']['field_rows'][0]['coverage'])

    def test_unsupported_type_operator_and_signature_reject(self):
        from wqb.hypothesis_design import compile_hypothesis_design
        resource = self.read_resources()
        design = self.normalized(resource)
        for mutation in ('type', 'operator', 'signature'):
            changed = deepcopy(resource)
            if mutation == 'type':
                changed['field_rows'][0]['field_type'] = 'UNSUPPORTED'
            elif mutation == 'operator':
                changed['operator_rows'] = []
            else:
                changed['operator_rows'][0]['definition']['parameters'][0]['type'] = 'VECTOR'
            with self.subTest(mutation=mutation):
                self.assertEqual(compile_hypothesis_design(design, changed, self.scope)['status'], 'rejected')

    def test_direct_wiki_access_and_legacy_raw_only_boundary(self):
        from wqb.research_queries import query_knowledge
        from wqb.research_query_index import prepare_query_index
        path = self.root / 'wiki/experience.md'
        path.parent.mkdir()
        path.write_text('Compiled experience; timing unknown.', encoding='utf-8')
        generation = prepare_query_index(self.root)['generation']
        with self.assertRaises(ValueError):
            query_knowledge(self.root, generation, self.scope, 'source', dict(path='wiki/experience.md'))
        result = query_knowledge(self.root, generation, self.scope, 'source',
            dict(path='wiki/experience.md'), direct_knowledge_version=1)
        source = result['items'][0]['source_refs'][0]
        self.assertEqual(source['source_type'], 'compiled_wiki')
        self.assertIsNone(source['captured_at'])
        self.assertFalse(source['platform_capture'])
        for relative in ('wiki/../machine/source_index.jsonl', 'wiki/.obsidian/config.md',
                         'machine/credentials.json', '../secret.md'):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                query_knowledge(self.root, generation, self.scope, 'source', dict(path=relative),
                    direct_knowledge_version=1)

    def test_valid_tree_seals_and_malformed_tree_rejects(self):
        from wqb import initial_research_planning as planning
        from wqb.execution_package import load_execution_package
        resource = self.read_resources()
        design = self.normalized(resource)
        design.pop('design_id')
        reverse = deepcopy(design)
        reverse['prediction_direction'] = 'negative'
        answer = dict(summary='Offline direct tree.', designs=[design, reverse],
            tree=dict(roots=['root'], nodes=[dict(node_id='root', parent_id=None,
                parent_arm_id=None, design_index=0, targets=dict(baseline=[], treatment=[]),
                fallback=[], reverse={arm: dict(design_index=1, arm_id=arm,
                    interpretation='Opposite direction is a hypothesis.', targets=[])
                    for arm in ('baseline', 'treatment')})]))
        for malformed in (True, False):
            run = self.root / ('bad-lane' if malformed else 'lane')
            run.mkdir()
            policy = dict(paired_scout=True, exploration_scout=True, exploration_policy_version=1,
                preplanned_tree_version=1, execution_package_version=1, direct_knowledge_version=1)
            manifest = dict(run_id=run.name, knowledge_root=str(self.root), selected_scope=self.scope,
                start_snapshot=dict(selected_scope=self.scope, research_policy=policy,
                    measurement_period=dict(start='2020-01-01', end='2025-01-01'),
                    repair_search_policy=dict(schema_version=1, rules=[], traits={})))
            (run / 'run_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

            def runner(brief):
                """Input: strict brief dict. Output: local fixture answer, no model/network calls."""
                proposed = deepcopy(answer)
                proposed['data_characteristics'] = [dict(dataset_id=row['dataset_id'],
                    field_id=row['field_id'], known_trait_keys=[], unknown_trait_keys=row['unknown_trait_keys'],
                    hypotheses=[], suggested_repair_rule_ids=[]) for row in brief['annotation_context']['fields']]
                if malformed:
                    proposed['tree']['roots'] = ['absent']
                return proposed

            with patch('wqb.exploration_eligibility.verify_source_equivalence',
                       side_effect=AssertionError('legacy certificate dependency')):
                result = planning.prepare_initial_research(run, self.root, resource, model_runner=runner,
                    template_receipts=[], tree_policy=dict(schema_version=1, plan_depth=2, initial_hypotheses=2))
            self.assertEqual(result['status'], 'blocked' if malformed else 'completed', result)
            if not malformed:
                package = load_execution_package(run)
                self.assertEqual(package['seal']['run_id'], run.name)
                certificate = package['manifest']['start_snapshot']['exploration_context']['resource_certificates'][0]
                self.assertEqual(certificate['policy']['direct_knowledge_version'], 1)

    def test_invalid_marker_rejects(self):
        from wqb.direct_knowledge import direct_knowledge_enabled
        for value in (True, 2, '1', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                direct_knowledge_enabled(dict(direct_knowledge_version=value))
        self.assertFalse(direct_knowledge_enabled({}))

    def test_console_loads_direct_policy_without_secret_or_legacy_admission(self):
        from tests.test_console_start import make_paths
        from wqb.console_start import load_start_config
        paths = make_paths(self.root / 'console')
        directory = paths.configuration_root / 'configs'
        directory.mkdir(parents=True, exist_ok=True)
        config = dict(research_policy=dict(preplanned_tree_version=1, execution_package_version=1,
            retrieval_design_version=1, direct_knowledge_version=1))
        path = directory / 'workflow_local.json'
        path.write_text(json.dumps(config), encoding='utf-8')
        actual = load_start_config(paths)
        self.assertEqual(actual['direct_knowledge_version'], 1)
        self.assertEqual(actual['resource_admission_policy'], 'direct_knowledge_v1')
        config['research_policy']['direct_knowledge_version'] = True
        path.write_text(json.dumps(config), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_start_config(paths)

    def test_direct_start_seals_with_current_machine_only(self):
        from types import SimpleNamespace
        from wqb.preplanned_start import prepare_preplanned_start
        from wqb.benchmark_rules import (benchmark_rules_path_for_knowledge,
            default_benchmark_rules, write_benchmark_rules_jsonl)
        from tests.test_workflow_stage_adapters import valid_option
        from tests import test_initial_research_planning as fixtures
        from wqb.execution_package import load_execution_package
        fixture = fixtures.InitialResearchPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        paths = SimpleNamespace(knowledge_root=self.root, run_root=self.root / 'runs',
            workflow_root=self.root, project_root=self.root)
        write_benchmark_rules_jsonl(benchmark_rules_path_for_knowledge(self.root), default_benchmark_rules())
        option = valid_option(option_id='direct-test')
        option['candidate_scope'] = f"{self.scope['region']} D{self.scope['delay']} {self.scope['universe']}"
        config = dict(DEFAULT_CONFIG, selected_scope=self.scope, measurement_period=fixture.period, parallel_workflows=1,
            direct_knowledge_version=1, research_policy=dict(execution_package_version=1,
                preplanned_tree_version=1), **dict(instrument_type='EQUITY',
                region=self.scope['region'], delay=self.scope['delay'], universe=self.scope['universe']))

        def runner(brief):
            """Input: source-bound brief dict. Output: strict offline answer with unknown properties unchanged."""
            proposed = deepcopy(fixture.answer)
            normalized = self.normalized(self.read_resources())
            for design in proposed['designs']:
                for key in ('field_roles', 'trigger_id', 'evidence_refs'):
                    design[key] = deepcopy(normalized[key])
            proposed['data_characteristics'] = [dict(dataset_id=row['dataset_id'], field_id=row['field_id'],
                known_trait_keys=[], unknown_trait_keys=row['unknown_trait_keys'], hypotheses=[],
                suggested_repair_rule_ids=[]) for row in brief['annotation_context']['fields']]
            return proposed

        result = prepare_preplanned_start(paths, option,
            dict(enable_live_api=False, max_runtime_seconds=3600, max_recoveries=3), config,
            model_runner=runner)
        self.assertEqual(result['status'], 'completed', result)
        run = paths.run_root / result['group']['lanes'][0]['run_id']
        package = load_execution_package(run)
        self.assertEqual(package['manifest']['start_snapshot']['research_policy']['direct_knowledge_version'], 1)
        self.assertFalse((self.root / 'machine/semantic_jobs').exists())
