"""Producer-owned resource policy, independent of economic completeness."""
import unittest
from copy import deepcopy
import json
import hashlib

from wqb import resource_evidence
from wqb.template_binding import bind_template, TemplateBindingError
from tests.test_template_binding import binding_fixture
from unittest.mock import patch


class ResourceAdmissionTests(unittest.TestCase):
    def test_absent_policy_preserves_old_behavior(self):
        self.assertFalse(resource_evidence.knowledge_catalog_admission({}))

    def test_explicit_catalog_policy_is_recognized(self):
        self.assertTrue(resource_evidence.knowledge_catalog_admission(
            {'resource_admission_policy': 'knowledge_catalog_v1'}))

    def test_unknown_or_coerced_policy_is_rejected(self):
        for value in (None, True, 1, '', 'knowledge_catalog_v2', {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                resource_evidence.knowledge_catalog_admission({'resource_admission_policy': value})


class CatalogBindingTests(unittest.TestCase):
    def test_unknown_economic_metadata_does_not_prevent_typed_binding(self):
        template, fields, operators, scope = binding_fixture()
        for row in fields:
            row.pop('units')
            row.pop('available_at')
        result = bind_template(template, fields, operators, scope, resource_contract_version=2,
            evidence_context={'resource_admission_policy': 'knowledge_catalog_v1'})
        self.assertEqual(result['bound_expression'], 'rank(cash / debt)')
        self.assertNotIn('units', result['bindings']['flow']['metadata'])
        self.assertNotIn('timing_receipt', result['bindings']['flow'])
        with self.assertRaises(TemplateBindingError):
            bind_template(template, fields, operators, scope, resource_contract_version=2)

    def test_identity_selector_does_not_invent_economic_semantics(self):
        template, fields, operators, scope = binding_fixture()
        for slot, row in zip(template['input_slots'], fields):
            row['field_description'] = ''
            slot['required_semantics'] = ['field:' + row['dataset_id'] + '/' + row['field_id']]
        result = bind_template(template, fields, operators, scope, resource_contract_version=2,
            evidence_context={'resource_admission_policy': 'knowledge_catalog_v1'})
        self.assertEqual(result['bound_expression'], 'rank(cash / debt)')

    def test_catalog_binding_keeps_ast_and_known_types(self):
        template, fields, operators, scope = binding_fixture()
        context = {'resource_admission_policy': 'knowledge_catalog_v1'}
        for skeleton in ('rank({flow}, {liability})', '__import__("os")', '{flow}.secret'):
            with self.subTest(skeleton=skeleton), self.assertRaises(TemplateBindingError):
                bind_template(dict(template, skeleton=skeleton), fields, operators, scope,
                    resource_contract_version=2, evidence_context=context)
        fields[0]['field_type'] = 'VECTOR'
        with self.assertRaises(TemplateBindingError):
            bind_template(template, fields, operators, scope, resource_contract_version=2,
                evidence_context=context)

    def test_catalog_mode_preserves_known_project_window_bounds(self):
        from tests.test_template_binding import project_window_fixture
        _, resources, scope, template = project_window_fixture()
        context = dict(source_index=resources['source_index'], source_texts=resources['source_texts'],
                       resource_admission_policy='knowledge_catalog_v1')
        for value in (0, -1, 2521):
            role = '{' + template['input_slots'][0]['name'] + '}'
            for argument in (str(value), 'd=' + str(value), '{window}'):
                candidate = dict(template, skeleton='ts_delta(' + role + ', ' + argument + ')')
                with self.subTest(value=value, argument=argument), self.assertRaises(TemplateBindingError):
                    bind_template(candidate, resources['field_rows'], resources['operator_rows'],
                        dict(scope, window=value), resource_contract_version=2, evidence_context=context)
        for value in (5, 22, 122, 252):
            candidate = dict(template, skeleton='ts_delta(' + role + ', ' + str(value) + ')')
            result = bind_template(candidate, resources['field_rows'], resources['operator_rows'], scope,
                resource_contract_version=2, evidence_context=context)
            self.assertIn(str(value), result['bound_expression'])

    def test_catalog_mode_preserves_project_default_parameter_bounds(self):
        from tests.test_template_binding import project_window_fixture
        for default in (0, -1, 2521):
            _, resources, scope, template = project_window_fixture(default=default)
            context = dict(source_index=resources['source_index'], source_texts=resources['source_texts'],
                           resource_admission_policy='knowledge_catalog_v1')
            template['skeleton'] = 'ts_delta({' + template['input_slots'][0]['name'] + '})'
            with self.subTest(default=default), self.assertRaises(TemplateBindingError):
                bind_template(template, resources['field_rows'], resources['operator_rows'], scope,
                    resource_contract_version=2, evidence_context=context)

    def test_catalog_mode_cannot_take_the_untyped_legacy_binding_path(self):
        template, fields, operators, scope = binding_fixture()
        template['binding_version'] = 1
        template['skeleton'] = 'rank({field})'
        with self.assertRaises(TemplateBindingError):
            bind_template(template, fields[:1], operators, scope, resource_contract_version=2,
                evidence_context={'resource_admission_policy': 'knowledge_catalog_v1'})


class CatalogCompilerTests(unittest.TestCase):
    def fixture(self, *, treatment=False):
        """Input: none. Output: exploratory design/resources/scope with optional economic metadata absent."""
        from tests.test_hypothesis_design import compiler_fixture
        design, resources, scope = compiler_fixture('level' if treatment else 'change', treatment=treatment)
        for target in (resources, resources['evidence_pack']):
            target['resource_contract_version'] = 2
            target['resource_admission_policy'] = 'knowledge_catalog_v1'
        for row in resources['field_rows']:
            row.pop('units', None)
            row.pop('available_at', None)
        resources['operator_rows'][0]['definition']['description'] = 'Economic use remains an exploratory hypothesis.'
        return {key: value for key, value in design.items() if key != 'design_id'}, resources, scope

    def test_catalog_compiles_without_economic_meaning_certification(self):
        from wqb.hypothesis_design import validate_hypothesis_design, compile_hypothesis_design
        from wqb.semantic_contracts import SemanticPolicy
        raw, resources, scope = self.fixture()
        design = validate_hypothesis_design(dict(summary='Exploratory assumption.', designs=[raw]),
            resources['evidence_pack'], SemanticPolicy())['designs'][0]
        result = compile_hypothesis_design(design, resources, scope)
        self.assertEqual(result['status'], 'compiled', result)
        self.assertIn('ts_delta(', result['experiment']['arms'][0]['binding']['bound_expression'])

    def test_catalog_cannot_contradict_documented_technical_signature(self):
        from wqb.hypothesis_design import validate_hypothesis_design, compile_hypothesis_design
        from wqb.semantic_contracts import SemanticPolicy
        raw, resources, scope = self.fixture()
        path = resources['operator_rows'][0]['definition']['evidence_refs'][0]['source_path']
        payload = json.loads(resources['source_texts'][path])
        payload['operators'][0]['definition']['output_type'] = 'VECTOR'
        text = json.dumps(payload)
        digest = hashlib.sha256(text.encode()).hexdigest()
        for target in (resources, resources['evidence_pack']):
            target['source_texts'][path] = text
            target['source_index'][path]['content_hash'] = digest
        for operator in resources['operator_rows']:
            for ref in operator['definition']['evidence_refs']:
                if ref['source_path'] == path:
                    ref['sha256'] = digest
        for ref in raw['evidence_refs']:
            if ref['source_path'] == path:
                ref['sha256'] = digest
        design = validate_hypothesis_design(dict(summary='Exploration.', designs=[raw]),
            resources['evidence_pack'], SemanticPolicy())['designs'][0]
        result = compile_hypothesis_design(design, resources, scope)
        self.assertEqual(result['status'], 'rejected', result)

    def test_ai_can_omit_unavailable_timing_requirements_without_changing_tree_schema(self):
        from wqb.hypothesis_design import validate_hypothesis_design
        from wqb.semantic_contracts import SemanticPolicy
        raw, resources, _ = self.fixture()
        for role in raw['field_roles']:
            role['required_metadata'] = []
        result = validate_hypothesis_design(dict(summary='Exploratory assumption.', designs=[raw]),
            resources['evidence_pack'], SemanticPolicy())
        self.assertEqual(result['designs'][0]['field_roles'][0]['required_metadata'], [])

    def test_catalog_marker_cannot_be_added_to_only_one_envelope(self):
        from wqb.hypothesis_template_compiler import _resources, CompilationError
        _, resources, scope = self.fixture()
        resources['evidence_pack'].pop('resource_admission_policy')
        with self.assertRaises(CompilationError):
            _resources(resources, scope)

    def test_model_brief_explains_catalog_unknowns_with_the_existing_tree_schema(self):
        from wqb.initial_research_planning import _brief, _policy, _output_schema
        _, resources, scope = self.fixture()
        manifest = {'start_snapshot': {'measurement_period': {'start': '2020-01-01', 'end': '2025-01-01'}}}
        certificate = {'scope': scope, 'content_sha256': '0' * 64}
        brief = _brief(resources, manifest, certificate, [], _policy({}))
        self.assertIn('knowledge_catalog_v1', brief['composition_contract'])
        self.assertIn('unknown', brief['composition_contract'])
        self.assertEqual(brief['output_schema'], _output_schema(2))

    def test_exploration_snapshot_preserves_admission_policy(self):
        from wqb.hypothesis_design import validate_hypothesis_design
        from wqb.semantic_contracts import SemanticPolicy
        from wqb.exploration_eligibility import validate_exploration, build_exploration_snapshot, validate_exploration_snapshot
        raw, resources, scope = self.fixture(treatment=True)
        design = validate_hypothesis_design(dict(summary='Exploration.', designs=[raw]),
            resources['evidence_pack'], SemanticPolicy())['designs'][0]
        receipt = validate_exploration(design, resources, scope)
        snapshot = build_exploration_snapshot([receipt])
        context = validate_exploration_snapshot(snapshot)
        self.assertEqual(snapshot['resource_admission_policy'], 'knowledge_catalog_v1')
        self.assertEqual(context['resource_admission_policy'], 'knowledge_catalog_v1')


class CatalogStartValidationTests(unittest.TestCase):
    def test_new_start_fills_planning_scope_not_field_availability(self):
        from tests.test_console_start import PreplannedConsoleStartTests
        from wqb.console_start import register_start
        from datetime import datetime
        case = PreplannedConsoleStartTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        config = deepcopy(case.config)
        config.pop('selected_scope')
        target = case.paths.configuration_root / 'configs/workflow_local.json'
        target.write_text(json.dumps(config), encoding='utf-8')
        request = register_start(case.paths, case.form, 'catalog-scope')
        selected = request['preplanned_config']['selected_scope']
        self.assertEqual(selected['instrument_type'], config['instrument_type'] if 'instrument_type' in config else 'EQUITY')
        self.assertIsNotNone(datetime.fromisoformat(selected['as_of']).tzinfo)
        self.assertEqual(request['preplanned_config']['measurement_period'], case.config['measurement_period'])
        self.assertNotIn('available_at', selected)

    def test_raw_certificate_accepts_verified_file_hash_enrichment(self):
        from tests.test_preplanned_start import PreplannedStartTests
        from wqb.group_preparation import prepare_group_lanes
        fixture = PreplannedStartTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        resource = deepcopy(fixture.resources[0])
        for path, row in resource['source_index'].items():
            row['file_sha256'] = hashlib.sha256((fixture.paths.knowledge_root / path).read_bytes()).hexdigest()
        resource['evidence_pack']['source_index'] = deepcopy(resource['source_index'])
        result = prepare_group_lanes(fixture.paths, [resource], fixture.scope,
            fixture.option, fixture.authority)
        self.assertEqual(len(result['certificates']), 1)

    def test_catalog_start_validation_does_not_require_timing_or_semantic_publication(self):
        from tests.test_preplanned_start import PreplannedStartTests
        from wqb.preplanned_start import _validate_resource
        fixture = PreplannedStartTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        resource = deepcopy(fixture.resources[0])
        for target in (resource, resource['evidence_pack']):
            target['resource_contract_version'] = 2
            target['resource_admission_policy'] = 'knowledge_catalog_v1'
        for row in resource['field_rows']:
            row.pop('available_at', None)
            row.pop('units', None)
        for operator in resource['operator_rows']:
            operator['definition']['description'] = 'Economic interpretation unknown.'
        actual = _validate_resource(fixture.paths.knowledge_root, resource, fixture.scope,
            resource['field_rows'], fixture.index)
        self.assertEqual(actual, resource)

    def test_new_console_preplanned_requests_select_catalog_mode(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from tests.test_console_state import make_paths
        from wqb.console_start import load_start_config
        with TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            target = paths.configuration_root / 'configs/workflow_local.json'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({'research_policy': {'preplanned_tree_version': 1}}), encoding='utf-8')
            config = load_start_config(paths)
            self.assertEqual(config['resource_admission_policy'], 'knowledge_catalog_v1')


class CatalogReadinessTests(unittest.TestCase):
    def test_valid_frozen_catalog_does_not_require_global_semantic_template_library(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from tests.test_workflow_auto_continue import write_start_artifacts
        from wqb.run_readiness import evaluate_run_readiness
        from wqb.template_library import template_library_path_for_knowledge
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_start_artifacts(root)
            vault = root / 'knowledge'
            path = template_library_path_for_knowledge(vault)
            path.unlink()
            snapshot = {'resource_admission_policy': 'knowledge_catalog_v1'}
            # Isolate artifact admission; source/receipt reconstruction has separate real compiler tests.
            with patch('wqb.hypothesis_selection.validate_operational_resource_context', return_value=snapshot), \
                    patch('wqb.run_readiness._validate_scope_artifacts'):
                report = evaluate_run_readiness(vault, 'research', live_api_enabled=True, start_snapshot=snapshot)
                self.assertFalse(any(i.level == 'block' and Path(i.path).name == path.name for i in report.issues), report)
                disabled = evaluate_run_readiness(vault, 'research', live_api_enabled=False, start_snapshot=snapshot)
                self.assertTrue(any(i.code == 'live_api_disabled' for i in disabled.issues))
            legacy = evaluate_run_readiness(vault, 'research', live_api_enabled=True)
            self.assertTrue(any(i.level == 'block' and Path(i.path).name == path.name for i in legacy.issues))

    def test_marker_without_valid_frozen_resources_does_not_waive_checks(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from tests.test_workflow_auto_continue import write_start_artifacts
        from wqb.run_readiness import evaluate_run_readiness
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_start_artifacts(root)
            report = evaluate_run_readiness(root / 'knowledge', 'research', live_api_enabled=True,
                start_snapshot={'resource_admission_policy': 'knowledge_catalog_v1'})
            self.assertTrue(report.blocked)
            self.assertTrue(any(i.code == 'invalid_catalog_context' for i in report.issues))


class CatalogModelWorkerTests(unittest.TestCase):
    def test_catalog_brief_crosses_the_existing_fake_readonly_worker(self):
        from tests.test_initial_model_worker import InitialModelWorkerTests
        from wqb.exploration_eligibility import certify_exploration_resources
        from wqb.initial_research_planning import _brief
        case = InitialModelWorkerTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        resources = deepcopy(case.fixture.resources)
        for target in (resources, resources['evidence_pack']):
            target['resource_contract_version'] = 2
            target['resource_admission_policy'] = 'knowledge_catalog_v1'
        for field in resources['field_rows']:
            field.pop('available_at', None)
            field.pop('units', None)
        certificate = certify_exploration_resources(case.run, case.fixture.knowledge, resources, case.fixture.scope)
        case.task['certificate'] = certificate
        case.task['brief'] = _brief(resources, case.fixture.manifest, certificate, [], case.fixture.policy)
        case.save_task()
        self.assertEqual(case.execute(), case.answer)

    def test_ai_output_cannot_choose_resource_admission_policy(self):
        from tests.test_initial_research_planning import InitialResearchPlanningTests
        from wqb.initial_research_planning import _output_schema
        from wqb.semantic_compilation import _check_schema
        case = InitialResearchPlanningTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        answer = dict(case.answer, resource_admission_policy='knowledge_catalog_v1')
        with self.assertRaises(ValueError):
            _check_schema(_output_schema(2), answer)


class CatalogTechnicalMaterialTests(unittest.TestCase):
    def material(self, *, output='MATRIX', append_json=False):
        """Input: declared Markdown output str/JSON flag. Output: exact-hash technical material without economic prose."""
        _, _, operators, _ = binding_fixture()
        operator = deepcopy(operators[0])
        body = ('### rank\n- Source id: `rank`\n- Input types: `MATRIX`\n'
                '- Output type: `' + output + '`\n- Parameters:\n'
                '  - `x0`: type=`MATRIX`, required=`true`\n')
        if append_json:
            definition = {key: value for key, value in operator['definition'].items() if key != 'evidence_refs'}
            body += '\n```json\n' + json.dumps(dict(operator='rank', definition=definition)) + '\n```\n'
        path = 'raw/platform/learn/technical.md'
        digest = hashlib.sha256(body.encode()).hexdigest()
        operator['definition']['evidence_refs'] = [dict(source_path=path, sha256=digest,
            capture_date='2026-11-05', kind='documented', experiment_refs=[])]
        index = {path: dict(path=path, content_hash=digest, captured_at='2026-11-05T00:00:00Z',
            source_type='platform_learn_material', source_family='raw/platform/learn')}
        return operator, index, {path: body}

    def test_technical_markdown_does_not_require_description(self):
        from wqb.resource_evidence import catalog_operator_definition
        operator, index, texts = self.material()
        result = catalog_operator_definition(operator, index, texts)
        self.assertEqual(result['output_type'], 'MATRIX')

    def test_description_absence_cannot_hide_conflicting_technical_fact(self):
        from wqb.resource_evidence import catalog_operator_definition
        operator, index, texts = self.material(output='VECTOR', append_json=True)
        with self.assertRaises(ValueError):
            catalog_operator_definition(operator, index, texts)
