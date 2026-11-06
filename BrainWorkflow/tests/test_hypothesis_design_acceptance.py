"""Offline structured-template integration; source fixtures are explicitly fictional."""

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from subprocess import CompletedProcess
from unittest.mock import patch
from pathlib import Path

from wqb import knowledge_compile
from wqb.semantic_contracts import SemanticPolicy
from tests.test_hypothesis_design import compiler_fixture


def audit_fixture(root: Path) -> tuple[dict, dict]:
    """Input: isolated root Path. Output: scope/template dicts. Write tiny explicitly sourced fake resources."""
    scope = dict(region='USA', delay=1, universe='TOP3000', as_of='2026-10-14T00:00:00Z')
    machine = root / 'machine'
    machine.mkdir(parents=True)
    raw = root / 'raw/platform/learn'
    raw.mkdir(parents=True)
    definition = dict(description='Ranks values.', input_types=['MATRIX'], output_type='MATRIX',
                      parameters=[dict(name='x', type='MATRIX', required=True)])
    operator_path = raw / 'operators.json'
    operator_path.write_text(json.dumps(dict(operator='rank', definition=definition)), encoding='utf-8')
    field = dict(id='cash', type='MATRIX', description='Cash balance', units='USD',
                 available_at='2026-10-12T00:00:00Z', dataset=dict(id='d'),
                 region='USA', delay=1, universe='TOP3000')
    field_path = raw / 'fields.json'
    field_path.write_text(json.dumps(field), encoding='utf-8')
    sources = []
    for path in (operator_path, field_path):
        sources.append(dict(path=path.relative_to(root).as_posix(),
            content_hash=hashlib.sha256(path.read_bytes()).hexdigest(), captured_at='2026-10-13T00:00:00Z',
            source_family='raw/platform/learn', source_type='platform_learn_material'))
    ref = dict(source_path=sources[0]['path'], sha256=sources[0]['content_hash'],
               capture_date='2026-10-13', kind='documented')
    operator = dict(operator='rank', definition=dict(definition, evidence_refs=[ref]))
    ledger = dict(field_id='cash', dataset_id='d', field_type='MATRIX', field_description='Cash balance',
                  units='USD', available_at=field['available_at'], semantic_tags=[],
                  source_paths=[sources[1]['path']], region='USA', delay=1, universe='TOP3000')
    for name, rows in [('source_index', sources), ('operator_ledger', [operator]),
                       ('template_library', []), ('data_ledger', [ledger])]:
        (machine / (name + '.jsonl')).write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    template = dict(template_id='cash-level', binding_version=2, skeleton='rank({signal})',
        input_slots=[dict(name='signal', role='signal', required_semantics=['Cash balance'],
                         field_type='MATRIX', required_metadata=['units'])])
    return scope, template


def reviewed_pair_knowledge(root: Path) -> tuple[Path, dict, dict]:
    """Input: isolated temporary Path. Output: vault/scope/command result; official producer and separate offline review."""
    from tests.test_hypothesis_pipeline import HypothesisSnapshotTests
    from tests.test_economic_hypothesis_acceptance import FakeCodexBoundary
    from wqb.semantic_compilation import design_review_identity, export_reviewed_design_proposals
    from wqb.semantic_publication import stage_semantic_release, publish_semantic_release
    knowledge, _ = HypothesisSnapshotTests().make_knowledge(root)
    decisions = knowledge / 'machine/decisions'
    decisions.mkdir()
    (knowledge / 'wiki/70_decisions/research_option_cards.jsonl').rename(decisions / 'research_option_cards.jsonl')
    (knowledge / 'wiki/70_decisions').rmdir()
    (knowledge / 'wiki/10_foundations/activity_snapshot.md').rename(knowledge / 'wiki/10_platform_rules.md')
    (knowledge / 'wiki/10_foundations').rmdir()
    design, resources, scope = HypothesisResourceAuditTests().page_pair_fixture()
    for row in resources['field_rows']:
        row.update(coverage=1, source_quality='platform_raw_capture', coverage_status='measured_raw',
                   source_updated_at='2026-10-13', compatible_template_ids=[])
    for row in resources['operator_rows']:
        row['semantic_status'] = 'reviewed'
    for relative, text in resources['source_texts'].items():
        target = knowledge / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode('utf-8'))
    for name, rows in (('data_ledger', resources['field_rows']), ('source_index', resources['source_index'].values())):
        (knowledge / ('machine/' + name + '.jsonl')).write_text(''.join(json.dumps(row) + '\n' for row in rows))
    answer = dict(summary='Offline sourced pair.', designs=[{k: v for k, v in design.items() if k != 'design_id'}])
    with FakeCodexBoundary(lambda payload, run: answer) as transport:
        result = knowledge_compile.compile_hypothesis_design_command(knowledge, dict(evidence_pack=resources['evidence_pack'],
            resources=resources, executor_argv=['fake', '{input}', '{output}']))
    if result['status'] != 'completed' or len(transport.calls) != 1:
        raise AssertionError(result)
    job = Path(result['job'])
    review = dict(design_review_identity(job, SemanticPolicy()), reviewer='independent-offline-reviewer',
                  reviewed_at='2026-10-16T00:00:00Z')
    proposals = export_reviewed_design_proposals(job, SemanticPolicy(), review)
    release = stage_semantic_release(knowledge, proposals, review['reviewed_at'])
    publish_semantic_release(knowledge, release)
    return knowledge, scope, result


class HypothesisResourceAuditTests(unittest.TestCase):
    def page_pair_fixture(self):
        """Input: TestCase. Output: design/resources/scope dicts. Combine lossless page operator and exact-field timing fixtures."""
        from tests.test_template_binding import project_window_fixture
        from tests.test_resource_evidence import page_operator_fixture, page_timing_fixture, replace_timing_capture
        from wqb.hypothesis_design import compile_hypothesis_design, validate_hypothesis_design
        design, resources, scope, _ = project_window_fixture()
        timing_fixture = page_timing_fixture()
        timing, field, scope, timing_index, timing_texts = timing_fixture
        captured = json.loads(timing_texts['raw/platform/data_fields/fields.jsonl'])
        captured['field']['description'] = 'negative relative sentiment volume'
        replace_timing_capture(timing_fixture, captured)
        field.update(timing_contract=timing, field_description='negative relative sentiment volume',
                     semantic_tags=[], source_paths=[timing['premises'][-1]['evidence_ref']['source_path']])
        resources['field_rows'] = [field]
        resources['settings'].update(region=scope['region'], universe=scope['universe'], delay=scope['delay'])
        design['field_roles'][0].update(required_semantics=['negative relative sentiment volume'],
                                        required_metadata=['timing_contract'])
        resources['evidence_pack']['allowed_role_semantics'] = ['negative relative sentiment volume']
        operator, index, texts = page_operator_fixture()
        resources['operator_rows'] = [operator]
        scope['as_of'] = '2026-10-16T00:00:00Z'
        for target in (resources, resources['evidence_pack']):
            target['source_index'].update(index)
            target['source_texts'].update(texts)
            target['source_index'].update(timing_index)
            target['source_texts'].update(timing_texts)
        resources['evidence_pack']['scope'] = scope
        design = validate_hypothesis_design(dict(summary='Offline page proof.', designs=[
            {key: value for key, value in design.items() if key != 'design_id'}]), resources['evidence_pack'], SemanticPolicy())['designs'][0]
        return design, resources, scope

    def test_page_backed_horizon17_pair_without_synthetic_operator_card(self):
        """Input: lossless offline page resources. Output: None. Bind distinct unreviewed Level/Change arms using sourced operation prose."""
        from wqb.hypothesis_design import compile_hypothesis_design
        design, resources, scope = self.page_pair_fixture()
        result = compile_hypothesis_design(design, resources, scope)
        self.assertEqual(result['status'], 'compiled', result)
        self.assertEqual(len(result['drafts']), 2)
        expressions = [arm['binding']['bound_expression'] for arm in result['experiment']['arms']]
        self.assertEqual(len(set(expressions)), 2)
        self.assertTrue(any('17' in expression for expression in expressions))
        self.assertTrue(all(draft['status'] == 'scout_only' and draft['semantic_status'] == 'unreviewed'
                            for draft in result['drafts']))

    def test_rehashed_numeric_restrictions_and_deleted_claims_block_pair_compilation(self):
        """Input: validly rehashed page mutations. Output: None. Horizon17 produces no drafts for restrictions or deleted source facts."""
        from tests.test_resource_evidence import DocumentationPageTests, PARENTHESIZED_WINDOW_CONSTRAINTS, UNRECOGNIZED_PARAMETER_CLAUSES
        from wqb.resource_evidence import validated_documentation_page
        from wqb.hypothesis_design import compile_hypothesis_design
        cases = [(0, 'TEXT', clause) for clause in ('d>=100.', 'd<10.', 'd &gt;= 100.', 'd &lt; 10.')]
        cases += [(0, 'TABLE', 'd>=100.'), (0, 'TABLE', 'd &lt; 10.')]
        cases += [(position, kind, clause) for position in (0, 1) for kind in ('TEXT', 'TABLE')
                  for clause in PARENTHESIZED_WINDOW_CONSTRAINTS + UNRECOGNIZED_PARAMETER_CLAUSES]
        cases += [(position, tag, '') for position in (0, 1) for tag in (
            'del', 's', 'strike', 'span hidden', 'span style="display:none"',
            'span style="text-decoration:line-through"', 'script', 'template')]
        for position, kind, clause in cases:
            design, resources, scope = self.page_pair_fixture()
            operator = resources['operator_rows'][0]
            fixture = operator, resources['source_index'], resources['source_texts']
            premise = [operator['definition_basis']['signature_premise'], *operator['definition_basis']['type_premises']][position]
            page = validated_documentation_page(premise['evidence_ref'], fixture[1], fixture[2])
            if clause:
                value = clause if kind == 'TEXT' else dict(data=[['Expression'], [clause]],
                    firstColIsHeader=False, firstRowIsTableHeader=False)
                if kind == 'TABLE' and clause == 'd>=100.':
                    value['data'] = [['d', '>=', '100']]
                if kind == 'TABLE' and clause == 'd &lt; 10.':
                    value['data'] = [['d', '&lt;', '10']]
                page['content'].append(dict(id='restriction', type=kind, value=value))
            else:
                block = page['content'][0 if position == 0 else 1]
                block['value'] = f'<{kind}>' + block['value'] + f'</{kind.split()[0]}>'
            DocumentationPageTests().replace_page(fixture, page, position)
            resources['evidence_pack']['source_index'] = resources['source_index']
            resources['evidence_pack']['source_texts'] = resources['source_texts']
            with self.subTest(position=position, kind=kind, clause=clause):
                result = compile_hypothesis_design(design, resources, scope)
                self.assertEqual(result['status'], 'rejected', result['rejections'])
                self.assertEqual(result['drafts'], [])

    def test_rehashed_full_page_timing_conflicts_block_pair_compilation(self):
        """Input: canonical full-page conflicting naming/cutoff. Output: None. A positive selected timing quote cannot create a pair."""
        from tests.test_resource_evidence import documentation_fixture
        from wqb.resource_evidence import validated_documentation_page
        from wqb.hypothesis_design import compile_hypothesis_design
        for kind in ('TEXT', 'TABLE'):
            design, resources, scope = self.page_pair_fixture()
            contract = resources['field_rows'][0]['timing_contract']
            ref = contract['premises'][1]['evidence_ref']
            page = validated_documentation_page(ref, resources['source_index'], resources['source_texts'])
            if kind == 'TABLE':
                value = copy.deepcopy(page['content'][1]['value'])
                value['data'][1][1], value['data'][2][1] = 'other', 'snt_buzz'
            else:
                value = 'Regular D1 Field: other Fast D1 Field: snt_buzz'
            page['content'].append(dict(id='conflict', type=kind, value=value))
            new_ref, index, texts = documentation_fixture(page)
            for target in (resources, resources['evidence_pack']):
                target['source_index'].update(index)
                target['source_texts'].update(texts)
            for position in (1, 2):
                contract['premises'][position]['evidence_ref'] = copy.deepcopy(new_ref)
            with self.subTest(kind=kind):
                result = compile_hypothesis_design(design, resources, scope)
                self.assertEqual(result['status'], 'rejected', result['rejections'])
                self.assertEqual(result['drafts'], [])

    def test_project_window_pair_horizon17(self):
        """Input: fictional new-rule pair. Output: None; compile two distinct horizon17 experiment arms."""
        from tests.test_template_binding import project_window_fixture
        from wqb.hypothesis_design import compile_hypothesis_design
        design, resources, scope, template = project_window_fixture()
        compiled = compile_hypothesis_design(design, resources, scope)
        self.assertEqual(compiled['status'], 'compiled', compiled)
        self.assertEqual(len(compiled['drafts']), 2)
        expressions = [arm['binding']['bound_expression'] for arm in compiled['experiment']['arms']]
        self.assertEqual(len(set(expressions)), 2)
        self.assertTrue(any('17' in expression for expression in expressions))

    def test_invalid_project_window_has_zero_executable_coverage(self):
        """Input: fictional sourced template with invalid d. Output: None; reject executable coverage without hiding operator facts."""
        from tests.test_template_binding import project_window_fixture
        _, resources, scope, template = project_window_fixture()
        for path, text in resources['source_texts'].items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode())
        for value in (17, 0, -1, 2521):
            with self.subTest(value=value):
                template['skeleton'] = f'ts_delta({{pulse}}, d={value})'
                audit = dict(resources, knowledge_root=self.root, template_rows=[template])
                result = knowledge_compile.semantic_resource_coverage(audit, scope)
                self.assertEqual(result['executable_bindings'], 1 if value == 17 else 0, result)

    def test_v2_coverage_uses_verified_policy_and_rejects_future_fact(self):
        from tests.test_hypothesis_design import source_backed_compiler_fixture
        from wqb.hypothesis_design import compile_hypothesis_design
        design, resources, scope = source_backed_compiler_fixture()
        for path, text in resources['source_texts'].items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode())
        compiled = compile_hypothesis_design(design, resources, scope)
        audit = dict(resources, knowledge_root=self.root, template_rows=compiled['drafts'])
        result = knowledge_compile.semantic_resource_coverage(audit, scope)
        self.assertEqual(result['executable_bindings'], 1, result)
        audit['field_rows'][0]['available_at'] = '2026-10-16T00:00:00Z'
        self.assertEqual(knowledge_compile.semantic_resource_coverage(audit, scope)['executable_bindings'], 0)

    def test_operator_basis_merge_never_silently_keeps_stale_proof(self):
        from tests.test_resource_evidence import operator_fixture
        row = operator_fixture()[0]
        changed = copy.deepcopy(row)
        changed['definition_basis']['rule_version'] = 99
        with self.assertRaisesRegex(ValueError, 'basis'):
            knowledge_compile._merge_operator_row(row, changed)
        changed = copy.deepcopy(row)
        changed['definition']['evidence_refs'].append(dict(
            source_path='raw/platform/learn/extra.md', sha256='f' * 64,
            capture_date='2026-10-15', kind='documented', experiment_refs=[]))
        with self.assertRaisesRegex(ValueError, 'basis'):
            knowledge_compile._merge_operator_row(row, changed)

    def setUp(self):
        """Input: TestCase. Output: None. Keep all files in a temporary vault."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.scope, self.template = audit_fixture(self.root)

    def test_audit_reads_real_contracts_without_writes_or_authority(self):
        before = {path.relative_to(self.root).as_posix(): path.read_bytes()
                  for path in self.root.rglob('*') if path.is_file()}
        result = knowledge_compile.audit_hypothesis_resources(self.root, self.scope, [self.template])
        self.assertEqual(result['coverage']['executable_bindings'], 1)
        self.assertEqual(result['coverage']['verified_field_rows'], 1)
        self.assertEqual(result['coverage']['verified_operator_rows'], 1)
        self.assertEqual(result['status'], 'usable_subset')
        self.assertTrue(result['partial'])
        self.assertFalse(result['research_authorized'])
        after = {path.relative_to(self.root).as_posix(): path.read_bytes()
                 for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_missing_timing_is_blocked_not_filled_from_capture_date(self):
        path = self.root / 'machine/data_ledger.jsonl'
        row = json.loads(path.read_text(encoding='utf-8'))
        del row['available_at']
        path.write_text(json.dumps(row) + '\n', encoding='utf-8')
        result = knowledge_compile.audit_hypothesis_resources(self.root, self.scope, [self.template])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['coverage']['executable_bindings'], 0)
        self.assertTrue(result['coverage']['reasons'])

    def test_tampered_source_is_not_rehashed_and_input_templates_unchanged(self):
        source = self.root / 'raw/platform/learn/fields.json'
        source.write_text(source.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        original = copy.deepcopy(self.template)
        result = knowledge_compile.audit_hypothesis_resources(self.root, self.scope, [self.template])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.template, original)
        self.assertTrue(any('content_hash mismatch' in row['reason'] for row in result['coverage']['reasons']))

    def test_audit_bounds_sample_and_does_not_call_it_full_coverage(self):
        path = self.root / 'machine/data_ledger.jsonl'
        row = json.loads(path.read_text(encoding='utf-8'))
        path.write_text(''.join(json.dumps(dict(row, field_id='field_' + str(i))) + '\n'
                                for i in range(40)), encoding='utf-8')
        result = knowledge_compile.audit_hypothesis_resources(self.root, self.scope, [])
        self.assertLessEqual(result['coverage']['scope_row_count'], 30)
        self.assertTrue(result['partial'])
        self.assertEqual(result['coverage']['executable_bindings'], 0)
        self.assertEqual(result['status'], 'blocked')

    def test_conflicting_index_rows_cannot_be_hidden_by_context_limit(self):
        path = self.root / 'machine/source_index.jsonl'
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        path.write_text(''.join(json.dumps(row) + '\n' for row in
            [rows[0]] * 9 + [dict(rows[0], content_hash='0' * 64), rows[1]]), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'conflicting source index'):
            knowledge_compile.audit_hypothesis_resources(self.root, self.scope, [self.template])

    def test_field_conflict_after_sample_cap_cannot_grant_executable_coverage(self):
        path = self.root / 'machine/data_ledger.jsonl'
        row = json.loads(path.read_text(encoding='utf-8'))
        rows = [row] + [dict(row, field_id='other_' + str(i), field_description='Other field') for i in range(29)]
        rows.append(dict(row, units='invented_units'))
        path.write_text(''.join(json.dumps(item) + '\n' for item in rows), encoding='utf-8')
        result = knowledge_compile.audit_hypothesis_resources(self.root, self.scope, [self.template])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['coverage']['executable_bindings'], 0)
        self.assertTrue(any(reason.get('code') == 'conflicting_field_identity' for reason in result['coverage']['reasons']))


class HypothesisDesignJobTests(unittest.TestCase):
    def test_official_page_producer_reaches_reviewed_paired_snapshot(self):
        from tests.test_hypothesis_pipeline import HypothesisSnapshotTests
        knowledge, scope, proposed = reviewed_pair_knowledge(self.root)
        snapshot = HypothesisSnapshotTests().paired_snapshot(knowledge, scope)
        self.assertEqual(len(snapshot['template_rows']), 2)
        self.assertTrue(all(row['semantic_status'] == 'unreviewed' for row in proposed['drafts']))

    def test_review_export_requires_exact_separate_authorization_and_never_publishes(self):
        from wqb import semantic_compilation as api
        self.use_source_backed_fixture()
        for row in self.resources['operator_rows']:
            row['semantic_status'] = 'reviewed'
        result = self.command()
        self.assertEqual(result['status'], 'completed', result)
        self.assertTrue(hasattr(api, 'design_review_identity'), 'official review producer missing')
        review = dict(api.design_review_identity(Path(result['job']), SemanticPolicy()),
                      reviewer='offline-reviewer', reviewed_at='2026-10-16T00:00:00Z')
        before = copy.deepcopy(result)
        for change in ({}, dict(review, result_digest='0' * 64), dict(review, reviewer='')):
            with self.assertRaises(ValueError):
                api.export_reviewed_design_proposals(Path(result['job']), SemanticPolicy(), change)
        exported = api.export_reviewed_design_proposals(Path(result['job']), SemanticPolicy(), review)
        self.assertEqual(result, before)
        self.assertFalse((self.root / 'machine/semantic_release.json').exists())
        self.assertTrue(all(r['status'] == 'scout_only' and r['semantic_status'] == 'reviewed'
                            for r in exported['validated_templates']))
        path = exported['validated_templates'][0]['experiment_paths'][0]
        wrapper = json.loads((self.root / path).read_text())
        self.assertEqual(set(wrapper), {'resource_contract_version', 'versions', 'compiler_input', 'experiment'})
        self.assertEqual(wrapper['experiment'], result['attachments'][0])
        self.assertEqual(exported, api.export_reviewed_design_proposals(Path(result['job']), SemanticPolicy(), review))
        (self.root / path).write_text('{}')
        with self.assertRaises(ValueError):
            api.export_reviewed_design_proposals(Path(result['job']), SemanticPolicy(), review)

    def test_selected_mechanism_feedback_is_hashed_bounded_and_not_measured(self):
        from tests.test_mechanism_evidence import evidence_fixture
        from wqb.mechanism_evidence import build_mechanism_evidence
        from wqb import semantic_compilation as api
        records, experiments = evidence_fixture()
        records[0]['backtest'][0]['error'] = 'timeout'
        view = build_mechanism_evidence(records, experiments)
        target = self.root / 'machine/mechanism_evidence.json'
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(view))
        config = dict(self.config, executor_argv=[], mechanism_query=dict(experiment_id='e'))
        first = self.command(config)
        self.assertEqual(first['status'], 'pending', first)
        job = Path(first['job'])
        material = json.loads((job / 'materials/pack.json').read_text())
        self.assertIn('mechanism_context', material['evidence_pack'], 'feedback not delivered')
        context = material['evidence_pack']['mechanism_context']
        self.assertEqual(context[0]['label'], 'operational_failure')
        self.assertEqual(material['evidence_pack'].get('histories', []), [])
        ref = context[0]['supporting_ref']
        raw = (job / ref['path']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), ref['sha256'])
        self.assertEqual(json.loads(raw), view['groups'][0])
        view['input_digest'] = 'unrelated-ledger-change'
        view['groups'].append(dict(view['groups'][0], group_id='unrelated', experiment_id='other',
                                   experiment=dict(experiment_id='other', arms=[])))
        target.write_text(json.dumps(view))
        self.assertEqual(first['job'], self.command(config)['job'])
        view['groups'][0]['observations'][0]['error'] = 'selected evidence bytes changed'
        target.write_text(json.dumps(view))
        self.assertNotEqual(first['job'], self.command(config)['job'])
        (job / ref['path']).write_text('{}')
        with self.assertRaises(ValueError):
            api.verify_design_materials(job, json.loads((job / 'run_manifest.json').read_text()), SemanticPolicy())

    def test_feedback_contract_binds_worker_and_does_not_legalize_empirical_claims(self):
        from wqb.hypothesis_design import DESIGN_WORKER_CONTRACT
        self.assertIn('explicit new experiment', DESIGN_WORKER_CONTRACT['instructions'])
        self.assertIn('not causal', DESIGN_WORKER_CONTRACT['instructions'])
        from tests.test_mechanism_evidence import evidence_fixture
        from wqb.mechanism_evidence import build_mechanism_evidence
        from wqb.semantic_compilation import prepare_design_job
        records, experiments = evidence_fixture()
        group = build_mechanism_evidence(records, experiments)['groups'][0]
        target = self.root / 'machine/mechanism_evidence.json'
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(dict(groups=[group], input_digest='irrelevant')))
        self.answer['designs'][0]['prediction'] = 'Backtest proved positive returns.'
        result = self.command(dict(self.config, mechanism_query=dict(experiment_id='e')))
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['drafts'], [])
        for maximum in (True, -1, 13):
            self.assertEqual(self.command(dict(self.config, mechanism_query=dict(experiment_id='e'),
                mechanism_maximum=maximum))['status'], 'blocked')
        with self.assertRaises(ValueError):
            prepare_design_job(self.root, self.pack, SemanticPolicy(), self.resources,
                               mechanism_feedback=[dict(group, claims='x' * 2_000_001)])
        empty = self.command(dict(self.config, executor_argv=[]))
        absent = self.command(dict(self.config, executor_argv=[], mechanism_query=dict(experiment_id='absent')))
        self.assertEqual(empty['job'], absent['job'])

    def test_feedback_omitted_eligible_history_does_not_change_frozen_job(self):
        from tests.test_mechanism_evidence import evidence_fixture
        from wqb.mechanism_evidence import build_mechanism_evidence
        from wqb.semantic_compilation import prepare_design_job
        records, experiments = evidence_fixture()
        view = build_mechanism_evidence(records, experiments)
        target = self.root / 'machine/mechanism_evidence.json'
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(view))
        config = dict(self.config, executor_argv=[], mechanism_query=dict(experiment_id='e'), mechanism_maximum=1)
        first = self.command(config)
        group = copy.deepcopy(view['groups'][0])
        group['group_id'] = 'z-omitted'
        view['groups'].append(group)
        view['input_digest'] = 'global digest must not bind the frozen job'
        target.write_text(json.dumps(view))
        self.assertEqual(first['job'], self.command(config)['job'])
        for value in (False, 0, {}, ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                prepare_design_job(self.root, self.pack, SemanticPolicy(), self.resources, mechanism_feedback=value)

    def test_review_export_binds_complete_selected_supporting_records(self):
        from tests.test_mechanism_evidence import evidence_fixture
        from wqb.mechanism_evidence import build_mechanism_evidence
        from wqb import semantic_compilation as api
        from wqb.semantic_publication import stage_semantic_release
        self.use_source_backed_fixture()
        for row in self.resources['operator_rows']:
            row['semantic_status'] = 'reviewed'
        records, experiments = evidence_fixture()
        view = build_mechanism_evidence(records, experiments)
        target = self.root / 'machine/mechanism_evidence.json'
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(view))
        result = self.command(dict(self.config, mechanism_query=dict(experiment_id='e')))
        self.assertEqual(result['status'], 'completed', result)
        job = Path(result['job'])
        review = dict(api.design_review_identity(job, SemanticPolicy()), reviewer='offline-reviewer',
                      reviewed_at='2026-10-16T00:00:00Z')
        exported = api.export_reviewed_design_proposals(job, SemanticPolicy(), review)
        support = json.loads((job / 'materials/pack.json').read_text())['evidence_pack']['mechanism_context'][0]['supporting_ref']
        relative = job.relative_to(self.root).as_posix() + '/' + support['path']
        self.assertIn(dict(path=relative, sha256=support['sha256']), exported['source_refs'])
        (self.root / relative).write_bytes(b'{}')
        with self.assertRaises(ValueError):
            stage_semantic_release(self.root, exported, review['reviewed_at'])

    def test_horizon_defaults_are_not_a_grid_or_whitelist(self):
        """Input: defaults/invalid alternatives. Output: None; validate bounded integer choices without expanding designs."""
        from wqb import hypothesis_design as design
        self.assertEqual(design.DEFAULT_HORIZONS, (5, 22, 122, 252))
        self.assertEqual(design.normalize_horizon_defaults([17]), (17,))
        self.assertEqual(design.normalize_horizon_defaults(design.DEFAULT_HORIZONS), design.DEFAULT_HORIZONS)
        for value in ([True], [False], [0], [-1], [design.MAX_HORIZON + 1], [17.0], [float('inf')], [], '17', {17}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                design.normalize_horizon_defaults(value)
        self.answer['designs'][0]['experiment_plan']['treatments'] = [dict(
            feature=dict(kind='change', input=dict(kind='role', role='pulse'), horizon=17),
            rationale='A seventeen day change tests the proposed response.')]
        result = design.validate_hypothesis_design(self.answer, self.pack, SemanticPolicy())
        self.assertEqual(len(result['designs']), 1)
        self.assertEqual(result['designs'][0]['experiment_plan']['treatments'][0]['feature']['horizon'], 17)

    def test_project_window_policy_binds_semantic_design_keys_and_worker_pack(self):
        """Input: project policy mutation. Output: None; whole policy affects keys and reaches frozen packs."""
        from wqb import resource_evidence
        from wqb.semantic_compilation import prepare_semantic_job
        self.use_source_backed_fixture()
        first = self.command(dict(self.config, executor_argv=[]))
        rows = list(self.pack['source_index'].values())
        semantic = prepare_semantic_job(self.root, rows, SemanticPolicy(), resource_version=2)
        pack = json.loads((Path(first['job']) / 'materials/pack.json').read_text())
        self.assertEqual(pack['parameter_policy'], resource_evidence.PROJECT_WINDOW_POLICY)
        manifest = json.loads((semantic / 'run_manifest.json').read_text())
        unit_pack = json.loads((semantic.parent / manifest['units'][0] / 'materials/pack.json').read_text())
        self.assertEqual(unit_pack['parameter_policy'], resource_evidence.PROJECT_WINDOW_POLICY)
        with patch.object(resource_evidence, 'PROJECT_WINDOW_POLICY', dict(
                resource_evidence.PROJECT_WINDOW_POLICY, policy_revision='test-only')):
            changed = self.command(dict(self.config, executor_argv=[]))
            changed_semantic = prepare_semantic_job(self.root, rows, SemanticPolicy(), resource_version=2)
        self.assertNotEqual(first['job'], changed['job'])
        self.assertNotEqual(semantic, changed_semantic)
        self.assertEqual(self.command(dict(self.config, executor_argv=[]))['job'], first['job'])
        self.assertEqual(self.calls, 0)

    def use_source_backed_fixture(self):
        """Input: TestCase. Output: None. Replace only temporary inputs with v2 offline sources."""
        from tests.test_hypothesis_design import source_backed_compiler_fixture
        design, self.resources, _ = source_backed_compiler_fixture()
        self.pack = self.resources['evidence_pack']
        self.answer = dict(summary='Source-backed proposal only.', designs=[{
            key: value for key, value in design.items() if key != 'design_id'}])
        for path, text in self.resources['source_texts'].items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode())
        self.config.update(evidence_pack=self.pack, resources=self.resources)

    def test_v2_compact_context_job_replay_and_worker_schema(self):
        from wqb.codex_ai_worker import run_worker
        from wqb.hypothesis_design import design_output_schema
        self.use_source_backed_fixture()
        first = self.command()
        self.assertEqual(first['status'], 'completed', first)
        self.assertEqual(first['attachments'][0]['resource_contract_version'], 2)
        self.assertEqual(self.command()['cache_status'], 'hit')
        self.assertEqual(self.calls, 1)
        job = Path(first['job'])
        material = json.loads((job / 'materials/pack.json').read_text())
        self.assertEqual(material['evidence_pack']['resource_contract_version'], 2)
        input_path = job / 'stages/ai/ai_checkpoint_runs/fake/attempt/input.json'
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(json.dumps(dict(checkpoint_type='hypothesis_design',
                                             evidence_paths=['materials/pack.json'])))
        def reply(argv, **kwargs):
            """Input: fake CLI argv. Output: CompletedProcess; inspect schema without a model."""
            schema = json.loads(Path(argv[argv.index('--output-schema') + 1]).read_text())
            self.assertEqual(schema, design_output_schema(2))
            self.assertNotIn('resource_contract_version', schema['properties'])
            Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(self.answer))
            return CompletedProcess(argv, 0, '', '')
        with patch('wqb.codex_ai_worker.shutil.which', return_value='fake'), patch(
                'wqb.codex_ai_worker.subprocess.run', side_effect=reply):
            self.assertEqual(run_worker(input_path, input_path.with_name('output.json')), self.answer)

    def test_semantic_worker_rejects_stale_policy_schema_and_identity_before_execution(self):
        """Input: frozen v2 fixture and changed contracts. Output: None; stale workers never invoke a model."""
        from wqb import resource_evidence, semantic_compilation as compilation
        from wqb.codex_ai_worker import run_worker
        self.use_source_backed_fixture()
        job = compilation.prepare_semantic_job(self.root, list(self.pack['source_index'].values()),
                                               SemanticPolicy(), resource_version=2)
        aggregate = json.loads((job / 'run_manifest.json').read_text())
        unit = job.parent / aggregate['units'][0]
        manifest_path = unit / 'run_manifest.json'
        original = json.loads(manifest_path.read_text())
        material_path = unit / 'materials/pack.json'
        original_pack = json.loads(material_path.read_text())
        material_path.chmod(0o600)
        manifest_path.chmod(0o600)
        input_path = unit / 'stages/ai/ai_checkpoint_runs/fake/attempt/input.json'
        input_path.parent.mkdir(parents=True)
        input_path.write_text(json.dumps(dict(checkpoint_type='semantic_compile',
                                             evidence_paths=['materials/pack.json'])))
        for mode in ('policy', 'missing_policy', 'bool_minimum', 'identity', 'schema', 'current_rules'):
            with self.subTest(mode=mode):
                manifest, pack = copy.deepcopy(original), copy.deepcopy(original_pack)
                if mode == 'policy':
                    pack['parameter_policy']['maximum'] = 1
                elif mode == 'missing_policy':
                    pack.pop('parameter_policy')
                elif mode == 'bool_minimum':
                    pack['parameter_policy']['minimum'] = True
                elif mode == 'identity':
                    manifest['identity']['parameter_policy']['maximum'] = 1
                elif mode == 'schema':
                    pack['schema_version'] = -1
                material_path.write_text(json.dumps(pack))
                manifest['material_refs'][0]['sha256'] = hashlib.sha256(material_path.read_bytes()).hexdigest()
                manifest_path.write_text(json.dumps(manifest))
                policy = dict(resource_evidence.PROJECT_WINDOW_POLICY,
                              policy_revision='changed') if mode == 'current_rules' else resource_evidence.PROJECT_WINDOW_POLICY
                with patch.object(resource_evidence, 'PROJECT_WINDOW_POLICY', policy), patch(
                        'wqb.codex_ai_worker.subprocess.run',
                        side_effect=AssertionError('stale semantic contract reached model execution')) as worker:
                    with self.assertRaises(ValueError):
                        run_worker(input_path, input_path.with_name('output.json'))
                    worker.assert_not_called()

    def test_semantic_schema_change_changes_key_and_rejects_old_cache(self):
        """Input: changed current output schema. Output: None; new key, no reinterpretation of old job."""
        from wqb import semantic_compilation as compilation
        self.use_source_backed_fixture()
        rows = list(self.pack['source_index'].values())
        job = compilation.prepare_semantic_job(self.root, rows, SemanticPolicy(), resource_version=2)
        schema = dict(compilation.semantic_output_schema(2), description='changed schema contract')
        with patch.object(compilation, 'semantic_output_schema', return_value=schema):
            changed = compilation.prepare_semantic_job(self.root, rows, SemanticPolicy(), resource_version=2)
            self.assertNotEqual(job, changed)
            result = compilation.compile_semantic_proposals(job, [], SemanticPolicy())
        self.assertEqual(result['cache_status'], 'invalid')
        self.assertFalse(result['validated_operators'])
        self.assertEqual(self.calls, 0)

    def test_current_semantic_worker_receives_project_policy_and_v2_schema(self):
        """Input: current frozen v2 fixture. Output: None; valid worker consumes explicit policy with a fake transport."""
        from wqb import semantic_compilation as compilation
        from wqb.codex_ai_worker import run_worker
        self.use_source_backed_fixture()
        job = compilation.prepare_semantic_job(self.root, list(self.pack['source_index'].values()),
                                               SemanticPolicy(), resource_version=2)
        aggregate = json.loads((job / 'run_manifest.json').read_text())
        unit = job.parent / aggregate['units'][0]
        material = json.loads((unit / 'materials/pack.json').read_text())
        input_path = unit / 'stages/ai/ai_checkpoint_runs/fake/attempt/input.json'
        input_path.parent.mkdir(parents=True)
        input_path.write_text(json.dumps(dict(checkpoint_type='semantic_compile',
                                             evidence_paths=['materials/pack.json'])))
        answer = dict(summary='No invented facts.', proposals=dict(operators=[], templates=[]))
        def reply(argv, **kwargs):
            """Input: fake CLI argv/kwargs. Output: CompletedProcess; inspect frozen evidence without a model."""
            schema = json.loads(Path(argv[argv.index('--output-schema') + 1]).read_text())
            self.assertEqual(schema, compilation.semantic_worker_schema(material))
            self.assertIn('ts_delta_project_window@2', argv[-1])
            self.assertIn('never reinterpret legacy ts_delta@1', argv[-1])
            self.assertIn('"parameter_policy":', argv[-1])
            self.assertIn('model_reasoning_effort=medium', argv)
            self.assertIn('read-only', argv)
            Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(answer))
            return CompletedProcess(argv, 0, '', '')
        with patch('wqb.codex_ai_worker.shutil.which', return_value='fake'), patch(
                'wqb.codex_ai_worker.subprocess.run', side_effect=reply):
            self.assertEqual(run_worker(input_path, input_path.with_name('output.json')), answer)

    def test_design_worker_explains_project_defaults_not_official_domain(self):
        """Input: frozen fictional design. Output: None; prompt preserves project/source distinction."""
        from wqb.codex_ai_worker import run_worker
        first = self.command(dict(self.config, executor_argv=[]))
        job = Path(first['job'])
        input_path = job / 'stages/ai/ai_checkpoint_runs/fake/attempt/input.json'
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(json.dumps(dict(checkpoint_type='hypothesis_design',
                                             evidence_paths=['materials/pack.json'])))
        def reply(argv, **kwargs):
            """Input: fake CLI argv/kwargs. Output: CompletedProcess; inspect actual prompt without a model."""
            self.assertIn('project-owned', argv[-1])
            self.assertIn('not an official platform domain', argv[-1])
            self.assertIn('one justified horizon', argv[-1])
            self.assertIn('not a whitelist', argv[-1])
            self.assertIn('exactly one sentence', argv[-1])
            self.assertIn('trigger_id must equal', argv[-1])
            self.assertIn('feature_plan must equal experiment_plan.baseline', argv[-1])
            self.assertIn('required_semantics must be a subset', argv[-1])
            self.assertIn('required_metadata must name only', argv[-1])
            self.assertIn('mechanism_family and condition_id must be ASCII identifiers', argv[-1])
            Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(self.answer))
            return CompletedProcess(argv, 0, '', '')
        with patch('wqb.codex_ai_worker.shutil.which', return_value='fake'), patch(
                'wqb.codex_ai_worker.subprocess.run', side_effect=reply):
            run_worker(input_path, input_path.with_name('output.json'))

    def test_design_worker_contract_changes_content_key(self):
        """Input: changed prompt contract. Output: assertions. Changed model instructions cannot replay a terminal key."""
        from wqb import hypothesis_design
        first = self.command(dict(self.config, executor_argv=[]))
        with patch.object(hypothesis_design, 'DESIGN_WORKER_CONTRACT', {'version': 999, 'instructions': 'Changed.'}):
            changed = self.command(dict(self.config, executor_argv=[]))
        self.assertNotEqual(first['job'], changed['job'])
        self.assertEqual(self.calls, 0)

    def test_changed_rule_or_source_changes_content_key(self):
        from wqb import resource_evidence
        self.use_source_backed_fixture()
        first = self.command(dict(self.config, executor_argv=[]))
        with patch.object(resource_evidence, 'OPERATOR_CONTEXT_POLICY_VERSION', 999):
            changed = self.command(dict(self.config, executor_argv=[]))
        self.assertNotEqual(first['job'], changed['job'])
        with patch.object(resource_evidence, 'REGULAR_DELAY_RULE', dict(resource_evidence.REGULAR_DELAY_RULE,
                                                                     rule_version=999)):
            changed_timing = self.command(dict(self.config, executor_argv=[]))
        self.assertNotEqual(first['job'], changed_timing['job'])
        self.assertEqual(self.calls, 0)

    def test_receipt_grammar_changes_content_key_without_model_execution(self):
        """Input: modified receipt policy dict. Output: assertions. Grammar changes invalidate terminal job identities."""
        from wqb import resource_evidence
        self.use_source_backed_fixture()
        first = self.command(dict(self.config, executor_argv=[]))
        changed_policy = dict(resource_evidence.OPERATOR_RECEIPT_POLICY, policy_revision='test-only')
        with patch.object(resource_evidence, 'OPERATOR_RECEIPT_POLICY', changed_policy):
            changed = self.command(dict(self.config, executor_argv=[]))
        self.assertNotEqual(first['job'], changed['job'])
        self.assertEqual(self.calls, 0)

    def test_v2_failed_and_changed_source_after_worker_never_replay_model(self):
        self.use_source_backed_fixture()
        def failure(argv, *args):
            """Input: fake worker argv. Output: failed CompletedProcess, no model."""
            self.calls += 1
            return CompletedProcess(argv, 1, '', 'offline failure')
        first = self.command(execute=failure)
        self.assertEqual(first['status'], 'blocked')
        self.assertEqual(self.command()['status'], 'blocked')
        self.assertEqual(self.calls, 1)
        self.resources['settings']['decay'] = 8
        def mutate(argv, *args):
            """Input: fake worker argv. Output: valid proposal, then change original source bytes."""
            result = self.execute(argv, *args)
            source = self.root / next(iter(self.pack['source_index']))
            source.write_bytes(source.read_bytes() + b'changed')
            return result
        self.assertEqual(self.command(execute=mutate)['status'], 'blocked')
        self.assertEqual(self.command()['status'], 'blocked')
        self.assertEqual(self.calls, 2)

    def test_v2_first_preparation_and_terminal_cancel_are_bounded(self):
        self.use_source_backed_fixture()
        with patch('wqb.ai_checkpoints._run_cancellable', side_effect=self.execute):
            results = self.first_call_pair(lambda: knowledge_compile.compile_hypothesis_design_command(
                self.root, self.config))
        self.assertEqual([row['status'] for row in results], ['completed', 'completed'],
                         [dict(status=row['status'], rejections=row.get('rejections')) for row in results])
        self.assertEqual(self.calls, 1)
        job = Path(results[0]['job'])
        (job / 'control.json').write_text('{"cancelled":true}')
        self.assertEqual(self.command()['status'], 'cancelled')
        (job / 'control.json').write_text('{"cancelled":false}')
        self.assertEqual(self.command()['status'], 'cancelled')
        self.assertEqual(self.calls, 1)

    def setUp(self):
        """Input: TestCase. Output: None. Freeze fictional full bytes in an isolated vault."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        design, self.resources, _ = compiler_fixture(treatment=True)
        self.pack = self.resources['evidence_pack']
        self.answer = dict(summary='Fictional proposal only.', designs=[{
            key: value for key, value in design.items() if key != 'design_id'}])
        for path, text in self.resources['source_texts'].items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode('utf-8'))
        self.config = dict(evidence_pack=self.pack, resources=self.resources,
                           executor_argv=['fake', '{input}', '{output}'])
        self.calls = 0

    def execute(self, argv, *args):
        """Input: fake process argv/unused protocol args. Output: CompletedProcess. No model/network."""
        self.calls += 1
        payload = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
        self.assertEqual(payload['checkpoint_type'], 'hypothesis_design')
        self.assertTrue(all(not Path(path).is_absolute() for path in payload['evidence_paths']))
        Path(argv[2]).write_text(json.dumps(self.answer), encoding='utf-8')
        return CompletedProcess(argv, 0, '', '')

    def command(self, config=None, execute=None):
        """Input: optional config/fake callable. Output: real bounded command result dict."""
        with patch('wqb.ai_checkpoints._run_cancellable', side_effect=execute or self.execute):
            return knowledge_compile.compile_hypothesis_design_command(self.root, config or self.config)

    def test_proposals_replay_without_publication_or_second_model_call(self):
        (self.root / 'machine').mkdir()
        protected = self.root / 'machine/active_semantic_release.json'
        protected.write_bytes(b'original release')
        frozen = self.root / 'runs/frozen/run_manifest.json'
        frozen.parent.mkdir(parents=True)
        frozen.write_bytes(b'original run')
        first, again = self.command(), self.command()
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(again['cache_status'], 'hit')
        self.assertEqual(self.calls, 1)
        self.assertEqual(first['designs'], again['designs'])
        self.assertEqual(first['attachments'], again['attachments'])
        self.assertTrue(first['drafts'])
        self.assertTrue(all(row['semantic_status'] == 'unreviewed' for row in first['drafts']))
        self.assertEqual(protected.read_bytes(), b'original release')
        self.assertEqual(frozen.read_bytes(), b'original run')
        self.assertFalse(first['research_authorized'])

    def test_prepare_freezes_full_sources_and_compact_relative_references(self):
        from wqb.codex_ai_worker import run_worker
        from wqb.hypothesis_design import design_output_schema
        job = knowledge_compile.prepare_hypothesis_design_job(self.root, self.pack, SemanticPolicy())
        manifest = json.loads((job / 'run_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['kind'], 'knowledge_compile')
        self.assertEqual(manifest['task_kind'], 'hypothesis_design')
        material = json.loads((job / manifest['material_refs'][0]['path']).read_text(encoding='utf-8'))
        self.assertNotIn('source_texts', material['evidence_pack'])
        for ref in manifest['supporting_material_refs']:
            self.assertEqual((job / ref['path']).read_bytes(),
                             (self.root / ref['source_path']).read_bytes())
        path = job / 'stages/ai/ai_checkpoint_runs/fake/attempt/input.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(checkpoint_type='hypothesis_design',
            evidence_paths=[manifest['material_refs'][0]['path']])), encoding='utf-8')
        def reply(argv, **kwargs):
            """Input: fake CLI args. Output: CompletedProcess. Assert schema and read-only/medium."""
            self.assertEqual(json.loads(Path(argv[argv.index('--output-schema') + 1]).read_text()),
                             design_output_schema(1))
            self.assertIn('model_reasoning_effort=medium', argv)
            self.assertIn('read-only', argv)
            self.assertIn('supporting_material_refs', argv[-1])
            Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(self.answer))
            return CompletedProcess(argv, 0, '', '')
        with patch('wqb.codex_ai_worker.shutil.which', return_value='fake'), patch(
                'wqb.codex_ai_worker.subprocess.run', side_effect=reply):
            output = run_worker(path, path.with_name('output.json'))
        self.assertEqual(output, self.answer)

    def test_failed_malformed_unknown_and_cancelled_keys_never_rerun(self):
        for mode in ('failure', 'malformed', 'unknown', 'cancel_before', 'cancel_after'):
            with self.subTest(mode=mode):
                config = copy.deepcopy(self.config)
                config['evidence_pack']['histories'] = []
                config['resources']['settings']['decay'] = len(mode)
                pending = self.command(dict(config, executor_argv=[]))
                job = Path(pending['job'])
                if mode == 'cancel_before':
                    (job / 'control.json').write_text('{"cancelled":true}')
                def reply(argv, *args):
                    """Input: fake argv. Output: process result. Inject one terminal failure."""
                    if mode == 'failure':
                        self.calls += 1
                        return CompletedProcess(argv, 1, '', 'fake failure')
                    result = self.execute(argv, *args)
                    if mode == 'malformed':
                        Path(argv[2]).write_text('{')
                    if mode == 'unknown':
                        Path(argv[2]).write_text(json.dumps(dict(self.answer, verdict='approved')))
                    if mode == 'cancel_after':
                        (job / 'control.json').write_text('{"cancelled":true}')
                    return result
                first = self.command(config, reply)
                self.assertIn(first['status'], ('blocked', 'cancelled'))
                calls = self.calls
                if (job / 'control.json').exists():
                    (job / 'control.json').write_text('{"cancelled":false}')
                again = self.command(config)
                self.assertIn(again['status'], ('blocked', 'cancelled'))
                self.assertEqual(self.calls, calls)

    def test_cache_and_material_tampering_fail_closed_without_rerun(self):
        for target in ('result.json', 'unit_result.json', 'materials/pack.json'):
            with self.subTest(target=target):
                config = copy.deepcopy(self.config)
                config['resources']['settings']['decay'] = len(target)
                first = self.command(config)
                self.assertEqual(first['status'], 'completed')
                path = Path(first['job']) / target
                path.chmod(0o666)
                path.write_text('{}')
                calls = self.calls
                again = self.command(config)
                self.assertEqual(again['status'], 'blocked')
                self.assertEqual(self.calls, calls)

    def test_source_validation_precedes_cache_reuse_and_compilation(self):
        first = self.command()
        source = self.root / next(iter(self.pack['source_index']))
        source.write_bytes(source.read_bytes() + b'changed')
        again = self.command()
        self.assertEqual(again['status'], 'blocked')
        self.assertEqual(self.calls, 1)
        self.assertEqual(again['drafts'], [])
        self.assertTrue(first['drafts'])

    def test_fabricated_text_and_unsafe_source_paths_are_rejected_before_execution(self):
        for path in ('../outside', '/absolute', 'raw/platform/../secret', 'raw/platform/credentials.txt'):
            with self.subTest(path=path):
                pack = copy.deepcopy(self.pack)
                row = next(iter(pack['source_index'].values()))
                pack['source_index'] = {path: dict(row, path=path)}
                pack.pop('source_texts')
                with self.assertRaises(ValueError):
                    knowledge_compile.prepare_hypothesis_design_job(self.root, pack, SemanticPolicy())
        self.resources['source_texts'][next(iter(self.pack['source_index']))] = 'fabricated'
        self.assertEqual(self.command()['status'], 'blocked')
        self.assertEqual(self.calls, 0)

    def test_settings_policy_and_versions_bind_content_key(self):
        from wqb import hypothesis_design, semantic_compilation
        first = self.command()
        config = copy.deepcopy(self.config)
        config['resources']['settings']['decay'] = 7
        changed = self.command(config)
        self.assertNotEqual(first['job'], changed['job'])
        for module, name in ((hypothesis_design, 'COMPILER_VERSION'),
                             (semantic_compilation, 'DESIGN_CONTEXT_VERSION')):
            with patch.object(module, name, 'future'):
                self.assertNotEqual(self.command()['job'], first['job'])
        config = dict(self.config, max_mechanisms=2)
        self.assertNotEqual(self.command(config)['job'], first['job'])

    def test_source_change_during_worker_blocks_before_pure_compiler(self):
        from wqb.hypothesis_design import compile_hypothesis_design
        def reply(argv, *args):
            """Input: fake argv. Output: result. Mutate original source after a valid answer."""
            result = self.execute(argv, *args)
            path = self.root / next(iter(self.pack['source_index']))
            path.write_bytes(path.read_bytes() + b'changed')
            return result
        with patch('wqb.hypothesis_design.compile_hypothesis_design', wraps=compile_hypothesis_design) as compiler:
            result = self.command(execute=reply)
        self.assertEqual(result['status'], 'blocked')
        compiler.assert_not_called()
        self.assertEqual(result['drafts'], [])

    def test_large_full_source_is_referenced_without_truncation(self):
        path = next(iter(self.pack['source_index']))
        text = self.pack['source_texts'][path] + (' complete fictional material' * 800)
        digest = hashlib.sha256(text.encode()).hexdigest()
        self.pack['source_index'][path]['content_hash'] = digest
        self.resources['source_index'][path]['content_hash'] = digest
        self.pack['source_texts'][path] = text
        self.resources['source_texts'][path] = text
        self.answer['designs'][0]['evidence_refs'][0]['sha256'] = digest
        (self.root / path).write_bytes(text.encode())
        result = self.command()
        self.assertEqual(result['status'], 'completed')
        job = Path(result['job'])
        manifest = json.loads((job / 'run_manifest.json').read_text())
        copy_ref = next(ref for ref in manifest['supporting_material_refs'] if ref['source_path'] == path)
        self.assertEqual((job / copy_ref['path']).read_bytes(), text.encode())
        self.assertLess((job / 'materials/pack.json').stat().st_size, 11000)

    def test_interrupted_checkpoint_and_unknown_cache_verdict_are_terminal(self):
        from wqb.ai_checkpoints import append_ai_checkpoint
        pending = self.command(dict(self.config, executor_argv=[]))
        job = Path(pending['job'])
        append_ai_checkpoint(job / 'stages/ai', 'hypothesis_design', 'Interrupted.',
                             ['materials/pack.json'], '2026-10-14T00:00:00Z')
        self.assertEqual(self.command()['status'], 'blocked')
        self.assertEqual(self.calls, 0)
        (job / 'result.json').write_text('{"cache_status":"approved"}')
        self.assertEqual(self.command()['status'], 'blocked')
        self.assertEqual(self.command()['status'], 'blocked')
        self.assertEqual(self.calls, 0)

    def test_concurrent_commands_share_one_checkpoint_attempt(self):
        from concurrent.futures import ThreadPoolExecutor
        self.command(dict(self.config, executor_argv=[]))
        with patch('wqb.ai_checkpoints._run_cancellable', side_effect=self.execute):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: knowledge_compile.compile_hypothesis_design_command(
                    self.root, self.config), range(2)))
        self.assertEqual([result['status'] for result in results], ['completed', 'completed'])
        self.assertEqual({result['cache_status'] for result in results}, {'ready', 'hit'})
        self.assertEqual(self.calls, 1)

    def first_call_pair(self, operation):
        """Input: no-arg callable. Output: two results. Exercise fresh copy creation concurrently."""
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier, Event, Lock
        start, lock = Barrier(2), Lock()
        arrivals = {}
        original_open = Path.open
        def open_copy(path, mode='r', *args, **kwargs):
            """Input: Path/open args. Output: file. Expose the first-copy exists/open race."""
            if mode == 'xb':
                with lock:
                    if str(path) in arrivals:
                        event = arrivals[str(path)]
                        event.set()
                    else:
                        event = arrivals[str(path)] = Event()
                # A serialized writer times out safely; a racing writer releases its peer.
                event.wait(0.2)
            return original_open(path, mode, *args, **kwargs)
        def run():
            """Input: none. Output: operation result. Start both callers without a prepared job."""
            start.wait(timeout=5)
            return operation()
        with patch.object(Path, 'open', open_copy):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(run) for _ in range(2)]
                return [future.result(timeout=10) for future in futures]

    def test_first_call_concurrent_commands_complete_and_replay_with_one_model_call(self):
        with patch('wqb.ai_checkpoints._run_cancellable', side_effect=self.execute):
            results = self.first_call_pair(lambda: knowledge_compile.compile_hypothesis_design_command(
                self.root, self.config))
        self.assertEqual([row['status'] for row in results], ['completed', 'completed'])
        self.assertEqual({row['cache_status'] for row in results}, {'ready', 'hit'})
        self.assertEqual(results[0]['job'], results[1]['job'])
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.command()['cache_status'], 'hit')
        self.assertEqual(self.calls, 1)

    def test_first_call_public_prepare_serializes_same_content_key(self):
        jobs = self.first_call_pair(lambda: knowledge_compile.prepare_hypothesis_design_job(
            self.root, self.pack, SemanticPolicy()))
        self.assertEqual(jobs[0], jobs[1])
        self.assertEqual(knowledge_compile.prepare_hypothesis_design_job(
            self.root, self.pack, SemanticPolicy()), jobs[0])
        self.assertEqual(self.calls, 0)

    @unittest.skipUnless(os.name == 'nt', 'Windows extended-path normalization regression')
    def test_first_prepare_never_anchors_guard_to_a_missing_job_directory(self):
        real_resolve = Path.resolve
        previous, missing_anchors = [None], []
        def resolve(path, *args, **kwargs):
            """Input: Path/resolve args. Output: Path. Replay observed mixed normal/extended prefix."""
            result = real_resolve(path, *args, **kwargs)
            if (path.parent.name == 'semantic_jobs' and len(path.name) == 64
                    and previous[0] == path / 'preparation_guard' and not path.exists()):
                missing_anchors.append(path)
                result = Path('\\\\?\\' + str(result))
            previous[0] = path
            return result
        with patch.object(Path, 'resolve', resolve):
            result = self.command()
            self.assertEqual(result['status'], 'completed')
            job = knowledge_compile.prepare_hypothesis_design_job(self.root, self.pack, SemanticPolicy())
            self.assertTrue((job / 'run_manifest.json').is_file())
        self.assertEqual(missing_anchors, [])

    def without_missing_parent_resolution(self, operation):
        """Input: callable. Output: result. Replay the same prefix race while job parents appear."""
        real_resolve = Path.resolve
        def resolve(path, *args, **kwargs):
            """Input: Path/resolve args. Output: Path. Expose unresolved parent creation on Windows."""
            result = real_resolve(path, *args, **kwargs)
            if path.name in {'machine', 'semantic_jobs'} and not path.exists():
                return Path('\\\\?\\' + str(result))
            return result
        with patch.object(Path, 'resolve', resolve):
            return operation()

    @unittest.skipUnless(os.name == 'nt', 'Windows extended-path normalization regression')
    def test_first_command_establishes_checked_parents_before_resolution(self):
        result = self.without_missing_parent_resolution(self.command)
        self.assertEqual(result['status'], 'completed')

    @unittest.skipUnless(os.name == 'nt', 'Windows extended-path normalization regression')
    def test_first_public_prepare_establishes_checked_parents_before_resolution(self):
        job = self.without_missing_parent_resolution(lambda: knowledge_compile.prepare_hypothesis_design_job(
            self.root, self.pack, SemanticPolicy()))
        self.assertTrue((job / 'run_manifest.json').is_file())

    def test_malformed_manifest_references_are_blocked_without_worker_or_exception(self):
        pending = self.command(dict(self.config, executor_argv=[]))
        path = Path(pending['job']) / 'run_manifest.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for key in ('material_refs', 'supporting_material_refs', 'context_refs', 'source_refs'):
            ref = original[key][0]
            cases = [None, 1, 'scalar', {}, [], [None], [1], ['scalar'], [[]], [{}],
                     [dict(ref, sha256=None)], [dict(ref, sha256='not-a-hash')],
                     [dict(ref, path=7)], [dict(ref, extra='unknown')], [ref, ref]]
            cases.extend([{name: value for name, value in ref.items() if name != missing}]
                         for missing in ref)
            for value in cases:
                with self.subTest(key=key, value=value):
                    path.write_text(json.dumps(dict(original, **{key: value})), encoding='utf-8')
                    calls = self.calls
                    result = self.command()
                    self.assertEqual(result['status'], 'blocked')
                    self.assertEqual(result['drafts'], [])
                    self.assertEqual(self.calls, calls)
        path.write_text(json.dumps(original), encoding='utf-8')

    def test_context_reference_hashes_exact_worker_visible_bytes(self):
        """Input: isolated prepared design. Output: assertions. Reject representation drift before a worker starts."""
        pending = self.command(dict(self.config, executor_argv=[]))
        job = Path(pending['job'])
        manifest = json.loads((job / 'run_manifest.json').read_text(encoding='utf-8'))
        ref = manifest['context_refs'][0]
        context = job / ref['path']
        self.assertEqual(hashlib.sha256(context.read_bytes()).hexdigest(), ref['sha256'])
        context.write_text(json.dumps(json.loads(context.read_text(encoding='utf-8')), indent=4), encoding='utf-8')
        calls = self.calls
        result = self.command()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.calls, calls)

    def test_fake_subprocess_roundtrip_persists_raw_designs_and_runs_only_once(self):
        from wqb.ai_checkpoints import load_ai_checkpoints
        code = (
            'import json,sys; from pathlib import Path; '
            'payload=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); '
            'assert payload["checkpoint_type"]=="hypothesis_design"; '
            f'Path(sys.argv[2]).write_text({json.dumps(self.answer)!r}, encoding="utf-8")'
        )
        config = dict(self.config, executor_argv=[sys.executable, '-c', code, '{input}', '{output}'])
        first = knowledge_compile.compile_hypothesis_design_command(self.root, config)
        again = knowledge_compile.compile_hypothesis_design_command(self.root, config)
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(again['cache_status'], 'hit')
        job = Path(first['job'])
        checkpoints = load_ai_checkpoints(job / 'stages/ai')
        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(checkpoints[0]['designs'], self.answer['designs'])
        self.assertNotIn('design_id', checkpoints[0]['designs'][0])
        events = (job / 'stages/ai/ai_checkpoint_events.jsonl').read_text(encoding='utf-8').splitlines()
        self.assertEqual([json.loads(row)['status'] for row in events], ['running', 'completed'])


if __name__ == '__main__':
    unittest.main()
