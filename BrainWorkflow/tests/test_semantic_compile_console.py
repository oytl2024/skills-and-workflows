"""Offline Task5 integration tests; no model, platform or real vault writes."""
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from wqb import knowledge_compile as compiler
from wqb.console_jobs import build_cli_command
from wqb.console_state import default_console_paths
from wqb.semantic_publication import read_semantic_release


class SemanticCompileConsoleTests(unittest.TestCase):
    def test_active_version_change_during_model_is_rechecked_before_merge(self):
        from wqb.semantic_publication import stage_semantic_release, publish_semantic_release
        active_pointer = []
        def compile_then_change_active(*args):
            """Input: fake compile args. Output: v1 proposals after a concurrent valid v2 publication."""
            proposals = dict(self.result, resource_contract_version=2,
                wiki_materials={'wiki/30_template_and_operator_patterns.md': '# Concurrent v2\n'})
            publish_semantic_release(self.root, stage_semantic_release(
                self.root, proposals, '2026-10-15T00:00:00Z'))
            active_pointer.append((self.root / 'machine/semantic_release.json').read_bytes())
            return self.result
        with patch('wqb.semantic_compilation.prepare_semantic_job',
                   return_value=self.root / 'machine/semantic_jobs/racing'), patch(
                'wqb.semantic_compilation.compile_semantic_proposals', side_effect=compile_then_change_active) as model:
            result = compiler.compile_semantic_knowledge_command(self.root, dict(source_refs=[], executor_argv=['fake']))
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result['status'], 'blocked', result)
        self.assertIn('resource contract downgrade', result['error'])
        self.assertEqual((self.root / 'machine/semantic_release.json').read_bytes(), active_pointer[0])

    def test_default_compile_cannot_downgrade_previous_v2_publication_or_call_model(self):
        from tests.test_resource_evidence import operator_fixture
        operator, _, texts = operator_fixture()
        refs = [self.ref]
        for path, text in texts.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode())
            refs.append(dict(path=path, sha256=hashlib.sha256(text.encode()).hexdigest()))
        first_result = dict(self.result, resource_contract_version=2,
                            validated_operators=[operator], source_refs=refs)
        first = self.invoke(first_result, resource_contract_version=2, _job_name='v2')
        self.assertEqual(first['status'], 'completed', first)
        self.assertEqual(first['release']['resource_contract_version'], 2)
        pointer = self.root / 'machine/semantic_release.json'
        before = {path.relative_to(self.root).as_posix(): path.read_bytes()
                  for base in (self.root / 'wiki', self.root / 'machine/semantic_releases')
                  for path in base.rglob('*') if path.is_file()}
        pointer_before = pointer.read_bytes()
        with patch('wqb.semantic_compilation.prepare_semantic_job',
                   return_value=self.root / 'machine/semantic_jobs/v1') as prepare, patch(
                'wqb.semantic_compilation.compile_semantic_proposals', return_value=self.result) as model:
            second = compiler.compile_semantic_knowledge_command(self.root,
                dict(source_refs=[], executor_argv=['fake']))
        self.assertEqual(second['status'], 'blocked', second)
        self.assertIn('resource contract', second['error'])
        prepare.assert_not_called()
        model.assert_not_called()
        self.assertEqual(pointer.read_bytes(), pointer_before)
        after = {path.relative_to(self.root).as_posix(): path.read_bytes()
                 for base in (self.root / 'wiki', self.root / 'machine/semantic_releases')
                 for path in base.rglob('*') if path.is_file()}
        self.assertEqual(after, before)

    def test_command_receipt_retries_transient_windows_sharing_conflict(self):
        from wqb import semantic_publication
        replace = semantic_publication.os.replace
        attempts = []
        def sharing_conflict(source, target):
            """Input: replacement paths. Output: None; inject one Windows receipt-read collision."""
            if Path(target).name == 'command_result.json':
                attempts.append(str(target))
                if len(attempts) == 1:
                    error = PermissionError('offline Windows sharing conflict')
                    error.winerror = 5
                    raise error
            return replace(source, target)
        with patch('wqb.semantic_publication.os.replace', side_effect=sharing_conflict):
            result = self.invoke()
        self.assertEqual(result['status'], 'completed', result)
        self.assertGreaterEqual(len(attempts), 2)

    def replace_coverage_capture(self, resources, raw):
        """Input: resource dict/raw JSON object. Output: None. Refresh isolated source bytes and index digest."""
        relative = resources['field_rows'][0]['source_paths'][0]
        path = self.root/relative
        path.write_text(json.dumps(raw)+'\n', encoding='utf-8')
        resources['source_index'][relative]['content_hash'] = hashlib.sha256(path.read_bytes()).hexdigest()

    def test_coverage_forged_semantic_tag_cannot_grant_binding(self):
        """Input: invented semantic tag. Output: None. Binder must consume only source-verified field meaning."""
        resources, scope = self.coverage_resources()
        resources['field_rows'][0]['semantic_tags'] = ['earnings surprise']
        resources['template_rows'][0]['input_slots'][0]['required_semantics'] = ['earnings surprise']
        result = compiler.semantic_resource_coverage(resources, scope)
        self.assertEqual(result['executable_bindings'], 0)
        self.assertEqual(resources['field_rows'][0]['semantic_tags'], ['earnings surprise'])
        path = self.root/resources['field_rows'][0]['source_paths'][0]
        raw = json.loads(path.read_text())
        raw['field']['semantic_tags'] = ['earnings surprise']
        self.replace_coverage_capture(resources, raw)
        self.assertEqual(compiler.semantic_resource_coverage(resources, scope)['executable_bindings'], 1)

    def test_coverage_checks_every_slot_declared_metadata_fact(self):
        """Input: custom required metadata. Output: None. Presence in the ledger cannot substitute for source facts."""
        resources, scope = self.coverage_resources()
        resources['field_rows'][0]['reporting_lag'] = 'T+0'
        resources['template_rows'][0]['input_slots'][0]['required_metadata'] = ['reporting_lag']
        self.assertEqual(compiler.semantic_resource_coverage(resources, scope)['executable_bindings'], 0)
        path = self.root/resources['field_rows'][0]['source_paths'][0]
        raw = json.loads(path.read_text())
        raw['field']['reporting_lag'] = 'T+0'
        self.replace_coverage_capture(resources, raw)
        self.assertEqual(compiler.semantic_resource_coverage(resources, scope)['executable_bindings'], 1)

    def test_coverage_unitless_level_and_group_have_minimal_inventory_requirements(self):
        """Input: source-backed fields without units. Output: None. Units are a slot requirement, not a universal gate."""
        resources, scope = self.coverage_resources()
        path = self.root/resources['field_rows'][0]['source_paths'][0]
        raw = json.loads(path.read_text())
        raw['field'].pop('units')
        resources['field_rows'][0].pop('units')
        resources['template_rows'][0]['input_slots'][0]['required_metadata'] = []
        self.replace_coverage_capture(resources, raw)
        result = compiler.semantic_resource_coverage(resources, scope)
        self.assertEqual(result['verified_field_rows'], 1)
        self.assertEqual(result['executable_bindings'], 1)
        raw['field']['type'] = 'GROUP'
        resources['field_rows'][0]['field_type'] = 'GROUP'
        resources['template_rows'] = []
        self.replace_coverage_capture(resources, raw)
        self.assertEqual(compiler.semantic_resource_coverage(resources, scope)['verified_field_rows'], 1)

    def test_coverage_unitless_group_binds_with_documented_group_operator(self):
        """Input: unitless grouping field and typed operator. Output: None. Keep legitimate grouped bindings executable."""
        resources, scope = self.coverage_resources()
        path = self.root/resources['field_rows'][0]['source_paths'][0]
        raw = json.loads(path.read_text())
        group = dict(scope=raw['scope'], data_set=raw['data_set'], field=dict(id='sector', type='GROUP',
            description='Sector membership', available_at=raw['field']['available_at']))
        self.replace_coverage_capture(resources, [raw, group])
        resources['field_rows'].append(dict(field_id='sector', dataset_id='d', field_type='GROUP',
            field_description='Sector membership', available_at=group['field']['available_at'],
            source_paths=resources['field_rows'][0]['source_paths'], **raw['scope']))
        operator = resources['operator_rows'][0]
        operator['operator'] = 'group_rank'
        definition = operator['definition']
        definition['description'] = 'Ranks within groups.'
        definition['input_types'].append('GROUP')
        definition['parameters'].append(dict(name='group', type='GROUP', required=True))
        ref = definition['evidence_refs'][0]
        source = self.root/ref['source_path']
        source.write_text(json.dumps(operator), encoding='utf-8')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        ref['sha256'] = digest
        resources['source_index'][ref['source_path']]['content_hash'] = digest
        template = resources['template_rows'][0]
        template['skeleton'] = 'group_rank({value}, {group})'
        template['input_slots'].append(dict(name='group', role='group', field_type='GROUP',
            required_semantics=['Sector membership'], required_metadata=[]))
        result = compiler.semantic_resource_coverage(resources, scope)
        self.assertEqual(result['verified_field_rows'], 2)
        self.assertEqual(result['executable_bindings'], 1)

    def test_coverage_flat_capture_binds_only_exact_sourced_facts(self):
        """Input: actual flat capture shape. Output: None. Preserve dataset/scope/metadata boundaries and absent availability."""
        resources, scope = self.coverage_resources()
        path = self.root/resources['field_rows'][0]['source_paths'][0]
        raw = json.loads(path.read_text())
        flat = dict(raw['field'], dataset=raw['data_set'], **raw['scope'])
        self.replace_coverage_capture(resources, flat)
        self.assertEqual(compiler.semantic_resource_coverage(resources, scope)['executable_bindings'], 1)
        for key, value in (('dataset', {'id': 'other'}), ('region', 'EUR'), ('type', 'VECTOR'),
                           ('units', 'shares'), ('available_at', None)):
            with self.subTest(key=key):
                self.replace_coverage_capture(resources, dict(flat, **{key: value}))
                result = compiler.semantic_resource_coverage(resources, scope)
                self.assertEqual(result['executable_bindings'], 0)
        flat.pop('available_at')
        resources['field_rows'][0].pop('available_at')
        self.replace_coverage_capture(resources, flat)
        result = compiler.semantic_resource_coverage(resources, scope)
        self.assertEqual(result['verified_field_rows'], 0)
        self.assertEqual(result['executable_bindings'], 0)

    def test_coverage_reports_unsupported_capture_format_explicitly(self):
        """Input: unrecognized structured source. Output: None. Separate unsupported format from absent field facts."""
        resources, scope = self.coverage_resources()
        self.replace_coverage_capture(resources, {'opaque_fields': ['cash']})
        result = compiler.semantic_resource_coverage(resources, scope)
        self.assertEqual(result['executable_bindings'], 0)
        self.assertTrue(any(reason.get('code') == 'unsupported_source_format' for reason in result['reasons']))

    def coverage_resources(self):
        """Input: TestCase. Output: resources dict. Build explicitly typed, source-bound offline facts."""
        from tests.test_semantic_contracts import evidence
        relative = 'raw/platform/operators/typed.md'
        body = ('### `rank`\n- Source id: `rank`\n- Description: Orders values.\n'
                '- Input types: `MATRIX`\n- Output type: `MATRIX`\n- Parameters:\n'
                '  - `x`: type=`MATRIX`, required=`true`\n')
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        ref = dict(evidence('documented'), source_path=relative, sha256=digest, capture_date='2026-10-11')
        operator = dict(operator='rank', definition=dict(description='Orders values.', input_types=['MATRIX'],
            output_type='MATRIX', parameters=[dict(name='x', type='MATRIX', required=True)], evidence_refs=[ref]))
        index = {relative: dict(path=relative, content_hash=digest, captured_at='2026-10-11T00:00:00Z',
            source_type='platform_learn_material', source_family='raw/platform/operators')}
        scope = dict(instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000', as_of='2026-10-14T00:00:00Z')
        raw = dict(scope={k: v for k, v in scope.items() if k != 'as_of'},
            data_set=dict(id='d'), field=dict(id='cash', type='MATRIX', description='Cash balance',
                units='USD', available_at='2020-01-01T00:00:00Z'))
        relative = 'raw/platform/data_fields/capture/data_fields.jsonl'
        path = self.root / relative
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(raw)+'\n', encoding='utf-8')
        index[relative] = dict(path=relative, content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            captured_at='2026-10-11T00:00:00Z', source_type='platform_data_field_capture',
            source_family='raw/platform/data_fields')
        field = dict(field_id='cash', dataset_id='d', field_type='MATRIX', field_description='Cash balance',
            units='USD', available_at=raw['field']['available_at'], source_paths=[relative], **raw['scope'])
        template = dict(template_id='probe', binding_version=2, skeleton='rank({value})', input_slots=[dict(
            name='value', role='level', field_type='MATRIX', required_semantics=['Cash balance'], required_metadata=['units'])])
        return dict(knowledge_root=self.root, source_index=index, field_rows=[field], operator_rows=[operator],
                    template_rows=[template]), scope

    def test_resource_coverage_counts_only_source_supported_actual_bindings(self):
        """Input: verified fixtures. Output: None. Distinguish materials, semantics and actual typed bindings."""
        resources, scope = self.coverage_resources()
        self.assertTrue(callable(getattr(compiler, 'semantic_resource_coverage', None)))
        result = compiler.semantic_resource_coverage(resources, scope)
        self.assertEqual((result['indexed_material'], result['verified_semantics'], result['executable_bindings']), (2, 2, 1))
        self.assertEqual(result['scope_row_count'], 1)
        self.assertEqual(result['unique_field_count'], 1)
        resources['field_rows'].append(dict(resources['field_rows'][0], dataset_id='other'))
        result = compiler.semantic_resource_coverage(resources, scope)
        self.assertEqual(result['executable_bindings'], 0)
        self.assertEqual(result['scope_row_count'], 2)
        self.assertEqual(result['unique_field_count'], 2)

    def test_resource_coverage_rejects_unbound_definition_api_label_and_missing_bytes(self):
        """Input: changed provenance/facts. Output: None. Reject borrowed IDs, unsupported labels and corrupt evidence."""
        self.assertTrue(callable(getattr(compiler, 'semantic_resource_coverage', None)))
        for mode in ('operator_id', 'api_label', 'hash', 'missing', 'no_root', 'field_units', 'field_timing'):
            with self.subTest(mode=mode):
                resources, scope = self.coverage_resources()
                relative = 'raw/platform/operators/typed.md'
                if mode == 'operator_id':
                    resources['operator_rows'][0]['operator'] = 'other'
                elif mode == 'api_label':
                    resources['source_index'][relative]['source_type'] = 'platform_api'
                elif mode == 'hash':
                    resources['source_index'][relative]['content_hash'] = '0'*64
                elif mode == 'missing':
                    (self.root/relative).unlink()
                elif mode == 'no_root':
                    resources.pop('knowledge_root')
                elif mode == 'field_units':
                    resources['field_rows'][0]['units'] = 'shares'
                else:
                    resources['field_rows'][0]['available_at'] = '2019-01-01T00:00:00Z'
                result = compiler.semantic_resource_coverage(resources, scope)
                if mode != 'field_units':
                    self.assertLess(result['verified_semantics'], 2)
                self.assertEqual(result['executable_bindings'], 0)
                self.assertTrue(result['reasons'])
                import shutil
                shutil.rmtree(self.root/'raw/platform/data_fields')

    def test_resource_coverage_rejects_conflicting_field_facts_in_same_source(self):
        """Input: conflicting same-scope raw facts. Output: None. A supporting row cannot hide contrary evidence."""
        resources, scope = self.coverage_resources()
        path = 'raw/platform/data_fields/capture/data_fields.jsonl'
        original = json.loads((self.root/path).read_text())
        other = json.loads(json.dumps(original))
        other['field']['units'] = 'shares'
        (self.root/path).write_text(json.dumps(original)+'\n'+json.dumps(other)+'\n', encoding='utf-8')
        resources['source_index'][path]['content_hash'] = hashlib.sha256((self.root/path).read_bytes()).hexdigest()
        result = compiler.semantic_resource_coverage(resources, scope)
        self.assertEqual(result['verified_field_rows'], 1)
        self.assertEqual(result['executable_bindings'], 0)


    def test_resource_coverage_rejects_presence_freshness_and_shape_only(self):
        """Input: unverified resources. Output: None. Row counts and plausible types cannot grant verified coverage."""
        from copy import deepcopy
        resources = dict(source_index={}, field_rows=[dict(field_id='f', dataset_id='d', field_type='MATRIX',
            region='USA', delay=1, universe='TOP3000', units='USD', available_at='2020-01-01T00:00:00Z',
            source_updated_at='2026-10-14', coverage=1, semantic_tags=['cash'])],
            operator_rows=[dict(operator='rank', definition=dict(description='Rank', input_types=['MATRIX'],
                output_type='MATRIX', parameters=[dict(name='x', type='MATRIX', required=True)], evidence_refs=[]))])
        original = deepcopy(resources)
        self.assertTrue(callable(getattr(compiler, 'semantic_resource_coverage', None)))
        result = compiler.semantic_resource_coverage(resources, dict(region='USA', delay=1, universe='TOP3000'))
        self.assertEqual(result['indexed_material'], 0)
        self.assertEqual(result['verified_semantics'], 0)
        self.assertEqual(result['executable_bindings'], 0)
        self.assertTrue(result['reasons'])
        self.assertEqual(resources, original)

    def setUp(self):
        """Input: TestCase. Output: None. Build an isolated source and legacy pair."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'knowledge'
        (self.root / 'machine').mkdir(parents=True)
        (self.root / 'wiki').mkdir()
        (self.root / 'raw/platform').mkdir(parents=True)
        source = self.root / 'raw/platform/definition.txt'
        source.write_text('rank orders observations.', encoding='utf-8')
        self.ref = dict(path='raw/platform/definition.txt', sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        self.old = dict(template_id='old', skeleton='rank({field})', hypothesis_id='h', hypothesis_version=1)
        (self.root / 'machine/template_library.jsonl').write_text(json.dumps(self.old)+'\n')
        (self.root / 'machine/operator_ledger.jsonl').write_text('{"operator":"rank"}\n')
        self.result = dict(validated_operators=[dict(operator='ts_delta')], validated_templates=[],
                           rejections=[], cache_status='ready', source_refs=[self.ref], coverage=dict(partial=True))

    def invoke(self, result=None, **config):
        """Input: fake validated output/config dict. Output: command result dict. Stub only Task3 worker boundary."""
        job = self.root / 'machine/semantic_jobs' / config.pop('_job_name', 'test')
        job.mkdir(parents=True, exist_ok=True)
        with patch('wqb.semantic_compilation.prepare_semantic_job', return_value=job), patch(
            'wqb.semantic_compilation.compile_semantic_proposals', return_value=result or self.result):
            return compiler.compile_semantic_knowledge_command(self.root, dict(source_refs=[], executor_argv=['fake'], **config))

    def test_console_maps_separate_semantic_mode_with_policy(self):
        paths = default_console_paths(self.root, Path(self.tmp.name)/'runs')
        command = build_cli_command('compile-semantic-knowledge', paths, dict(max_mechanisms=3, max_conditions_per_mechanism=2))
        self.assertIn('compile-semantic-knowledge', command)
        self.assertIn('--max-mechanisms', command)
        self.assertIn('--max-conditions-per-mechanism', command)
        self.assertNotIn('--enable-live-api', command)
        self.assertIn('compile-research-records', build_cli_command('compile-research-records', paths))

    def test_partial_publish_preserves_untouched_pair_and_reports_coverage(self):
        self.assertTrue(callable(getattr(compiler, 'compile_semantic_knowledge_command', None)), 'semantic command missing')
        result = self.invoke()
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['coverage']['partial'])
        receipt = read_semantic_release(self.root)
        self.assertEqual(result['release']['release_id'], receipt['release_id'])
        self.assertEqual([json.loads(x) for x in Path(receipt['paths']['template_library']).read_text().splitlines()], [self.old])
        self.assertEqual(len(Path(receipt['paths']['operator_ledger']).read_text().splitlines()), 2)

    def test_cancelled_output_does_not_publish(self):
        self.assertTrue(callable(getattr(compiler, 'compile_semantic_knowledge_command', None)), 'semantic command missing')
        result = self.invoke(dict(self.result, cache_status='cancelled'))
        self.assertEqual(result['status'], 'cancelled')
        self.assertIsNone(read_semantic_release(self.root)['release_id'])

    def test_same_template_id_changed_content_is_blocked(self):
        self.assertTrue(callable(getattr(compiler, 'compile_semantic_knowledge_command', None)), 'semantic command missing')
        result = self.invoke(dict(self.result, validated_templates=[dict(self.old, skeleton='-rank({field})')]))
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('unique template_id', result['error'])
        self.assertIsNone(read_semantic_release(self.root)['release_id'])

    def test_failed_model_is_persisted_with_notification(self):
        self.assertTrue(callable(getattr(compiler, 'compile_semantic_knowledge_command', None)), 'semantic command missing')
        result = self.invoke(dict(self.result, cache_status='failed', rejections=[dict(code='worker_failed', message='model unavailable')]))
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('model unavailable', json.dumps(result))
        self.assertIn('status', result['notification'])
        self.assertTrue((Path(result['job'])/'command_result.json').exists())

    def test_direct_migration_and_wiki_writers_refuse_active_release(self):
        self.assertTrue(callable(getattr(compiler, 'compile_semantic_knowledge_command', None)), 'semantic command missing')
        self.assertEqual(self.invoke()['status'], 'completed')
        from wqb.knowledge_vault_migration import run_knowledge_vault_migration
        from wqb.operator_semantics import compile_operator_semantics
        from wqb.knowledge_experience_compile import compile_human_experience_wiki
        for function in (run_knowledge_vault_migration, compile_operator_semantics, compile_human_experience_wiki):
            with self.assertRaisesRegex(ValueError, 'semantic'):
                function(self.root, '2026-10-13T00:00:00Z')

    def test_notification_failure_is_deduplicated(self):
        self.assertTrue(callable(getattr(compiler, 'compile_semantic_knowledge_command', None)), 'semantic command missing')
        result = self.invoke(dict(self.result, cache_status='failed'))
        from wqb.maintenance_notifications import dispatch_knowledge_notification
        with patch('wqb.maintenance_notifications.subprocess.run') as transport:
            again = dispatch_knowledge_notification(Path(result['job']), '2026-10-13T01:00:00Z')
        self.assertEqual(again, result['notification'])
        transport.assert_not_called()

    def test_missing_source_event_deduplicates_and_uses_correct_channel(self):
        from types import SimpleNamespace
        channel = self.root.parent/'runs/maintenance_channel.json'
        channel.parent.mkdir()
        channel.write_text('{"thread_id":"00000000-0000-0000-0000-000000000001"}')
        with patch('wqb.maintenance_notifications.shutil.which', return_value='fake-codex'), patch(
            'wqb.maintenance_notifications.subprocess.run', return_value=SimpleNamespace(returncode=0)) as transport:
            first = compiler.compile_semantic_knowledge_command(self.root, {})
            second = compiler.compile_semantic_knowledge_command(self.root, {})
        self.assertEqual(first['notification']['status'], 'queued', first)
        self.assertEqual(first['job'], second['job'])
        self.assertEqual(transport.call_count, 1)

    def test_cancel_after_publication_does_not_invalidate_completed_replay(self):
        from wqb.console_jobs import cancel_semantic_job
        first = self.invoke()
        control = cancel_semantic_job(self.root, Path(first['job']).name)
        self.assertFalse(control['cancelled'])
        self.assertFalse((Path(first['job'])/'control.json').exists())

    def test_policy_does_not_coerce_boolean_or_fractional_config(self):
        for value in (True, 1.5, 0):
            with patch('wqb.semantic_compilation.compile_semantic_proposals', return_value=self.result) as worker:
                result = compiler.compile_semantic_knowledge_command(self.root, dict(source_refs=[], max_mechanisms=value))
            self.assertEqual(result['status'], 'blocked', result)
            worker.assert_not_called()

    def test_console_status_cancel_and_timeline_show_knowledge_error(self):
        from wqb import console_jobs, console_state
        from wqb.console_timeline import build_timeline_rows
        self.assertTrue(callable(getattr(console_jobs, 'cancel_semantic_job', None)), 'knowledge cancellation missing')
        job = self.root/'machine/semantic_jobs/test'
        job.mkdir(parents=True)
        (job/'command_result.json').write_text(json.dumps(dict(status='blocked', error='missing operator definition', notification=dict(status='failed'))))
        summary = console_state._latest_semantic_compile(self.root)
        rows = build_timeline_rows(dict(semantic_compile=summary))
        row = next(row for row in rows if row['stage_id'] == 'knowledge_compile')
        self.assertEqual(row['status'], 'blocked')
        self.assertIn('missing operator definition', json.dumps(row))
        console_jobs.cancel_semantic_job(self.root, 'test')
        self.assertTrue(json.loads((job/'control.json').read_text())['cancelled'])

    def test_cli_parser_exposes_semantic_policy(self):
        from wqb.cli import parse_args
        with patch('sys.argv', ['wqb', 'compile-semantic-knowledge', '--max-mechanisms', '2', '--max-conditions-per-mechanism', '1']):
            args = parse_args()
        self.assertEqual((args.max_mechanisms, args.max_conditions_per_mechanism), (2, 1))

    def test_command_replay_keeps_release_and_does_not_publish_twice(self):
        first = self.invoke(generated_at='2026-10-13T00:00:00Z')
        with patch('wqb.semantic_publication.publish_semantic_release', wraps=__import__('wqb.semantic_publication', fromlist=['publish_semantic_release']).publish_semantic_release) as publish:
            second = self.invoke(generated_at='2026-10-13T01:00:00Z')
        self.assertEqual(first['release']['release_id'], second['release']['release_id'])
        publish.assert_not_called()

    def test_completed_replay_interruption_never_erases_receipt(self):
        first = self.invoke()
        job = Path(first['job'])
        with patch('wqb.semantic_compilation.prepare_semantic_job', return_value=job), patch(
            'wqb.semantic_compilation.compile_semantic_proposals', side_effect=KeyboardInterrupt):
            try:
                compiler.compile_semantic_knowledge_command(self.root, dict(source_refs=[], executor_argv=['fake']))
            except KeyboardInterrupt:
                pass
        self.assertEqual(json.loads((job/'command_result.json').read_text())['status'], 'completed')
        with patch('wqb.semantic_publication.publish_semantic_release') as publish:
            self.assertEqual(self.invoke()['release']['release_id'], first['release']['release_id'])
        publish.assert_not_called()

    def test_publish_interruption_recovers_same_staged_generation(self):
        from wqb.semantic_publication import publish_semantic_release
        def interrupted(root, release):
            """Input: vault Path/receipt dict. Output: never. Interrupt after atomic pointer publication."""
            publish_semantic_release(root, release)
            raise KeyboardInterrupt
        with patch('wqb.semantic_publication.publish_semantic_release', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.invoke()
        active = read_semantic_release(self.root)
        recovered = self.invoke(generated_at='2026-10-14T00:00:00Z')
        self.assertEqual(recovered['status'], 'completed', recovered)
        self.assertEqual(recovered['release']['release_id'], active['release_id'])

    def test_publish_oserror_keeps_commit_intent_for_recovery_and_cancel(self):
        from wqb.semantic_publication import publish_semantic_release
        from wqb.console_jobs import cancel_semantic_job
        def broken_wiki(root, release):
            """Input: vault Path/staged receipt. Output: never. Report an IO failure after committing the pair."""
            publish_semantic_release(root, release)
            raise OSError('wiki replacement unavailable')
        with patch('wqb.semantic_publication.publish_semantic_release', side_effect=broken_wiki):
            first = self.invoke()
        self.assertEqual(first['status'], 'blocked', first)
        active = read_semantic_release(self.root)
        self.assertFalse(cancel_semantic_job(self.root, 'test')['cancelled'])
        recovered = self.invoke(generated_at='2026-10-14T00:00:00Z')
        self.assertEqual(recovered['status'], 'completed', recovered)
        self.assertEqual(recovered['release']['release_id'], active['release_id'])

    def captured_operators(self, count):
        """Input: operator count int. Output: source index dict. Write isolated real captured Markdown."""
        from wqb.knowledge_contracts import render_front_matter
        body = '# Operators\n\n' + '\n'.join(f'### op{i}\n- Definition: op{i}(x) orders observations.\n' for i in range(count))
        row = dict(content_hash=hashlib.sha256(body.encode()).hexdigest(), captured_at='2026-10-13T00:00:00Z',
                   source_type='platform_learn_material', source_family='raw/platform/operators', path='raw/platform/operators/operators.md')
        (self.root/row['path']).parent.mkdir(parents=True, exist_ok=True)
        (self.root/row['path']).write_text(render_front_matter(row)+body, encoding='utf-8')
        (self.root/'machine/source_index.jsonl').write_text(json.dumps(row)+'\n')
        return row

    def proposals_for_targets(self, row, targets):
        """Input: index dict/target str list. Output: checkpoint dict. Propose unmeasured uses within actual Task3 scope."""
        ref = dict(source_path=row['path'], sha256=row['content_hash'], capture_date=row['captured_at'][:10], kind='hypothesis', experiment_refs=[])
        operators = [dict(trigger_id=target, mechanism_id='ordering', condition_id='comparable',
            record=dict(operator=target, family='normalizer', semantic_version=2, evidence_refs=[ref],
                conditional_uses=[dict(conditions='Comparable observations.', purpose='Test ordering.', failure_risks=['Noise.'], evidence_refs=[ref])])) for target in targets]
        return dict(status='completed', summary='Unmeasured hypotheses.', proposals=dict(operators=operators, templates=[]))

    def test_explicit_compiles_advance_missing_targets_then_hit_cache(self):
        row = self.captured_operators(7)
        calls = []
        def worker(directory, *args, **kwargs):
            """Input: checkpoint directory/args. Output: proposed checkpoint dict. Read the real frozen target scope."""
            manifest = json.loads((Path(directory).parents[1]/'run_manifest.json').read_text())
            targets = manifest['target_ids']
            calls.append(targets)
            return self.proposals_for_targets(row, targets)
        with patch('wqb.semantic_compilation.run_ai_checkpoint', side_effect=worker):
            results = [compiler.compile_semantic_knowledge_command(self.root, dict(executor_argv=['fake'])) for _ in range(4)]
        self.assertTrue(all(result['status'] == 'completed' for result in results), results)
        self.assertEqual(calls, [['op0', 'op1', 'op2'], ['op3', 'op4', 'op5'], ['op6']])
        self.assertEqual([result['coverage']['remaining_target_count'] for result in results], [4, 1, 0, 0])
        self.assertEqual(results[-1]['cache_status'], 'hit')
        self.assertEqual(read_semantic_release(self.root)['release_id'], results[2]['release']['release_id'])

    def test_source_bytes_change_invalidates_covered_target_selection(self):
        row = self.captured_operators(5)
        with patch('wqb.semantic_compilation.run_ai_checkpoint', return_value=self.proposals_for_targets(row, ['op0', 'op1', 'op2'])):
            self.assertEqual(compiler.compile_semantic_knowledge_command(self.root, dict(executor_argv=['fake']))['status'], 'completed')
        self.assertEqual(compiler._select_semantic_sources(self.root, [row])[0]['target_ids'], ['op3', 'op4'])
        source = self.root/row['path']
        source.write_bytes(source.read_bytes().replace(b'# Operators', b'# Operators changed'))
        self.assertEqual(compiler._select_semantic_sources(self.root, [row])[0]['target_ids'], ['op0', 'op1', 'op2'])

    def test_grouping_survives_publication_as_canonical_family(self):
        templates = [dict(template_id='new1', hypothesis_id='hyp1', hypothesis_version=1, skeleton='rank({field})', template_family=''),
                     dict(template_id='new2', hypothesis_id='hyp2', hypothesis_version=1, skeleton='-rank({field})', template_family='known-family')]
        grouping = [dict(kind='templates', record_id=row['template_id'], trigger_id='source-prefix', mechanism_id='ordering', condition_id='c') for row in templates]
        result = self.invoke(dict(self.result, validated_templates=templates, grouping=grouping))
        self.assertEqual(result['status'], 'completed', result)
        _, _, published = compiler.read_semantic_rows(self.root)
        families = {row['template_id']: row.get('template_family') for row in published}
        self.assertEqual(families['new1'], 'ordering')
        self.assertEqual(families['new2'], 'known-family')

    def test_normal_source_index_derives_bounded_targets_and_uses_real_task3(self):
        from wqb.knowledge_contracts import render_front_matter
        body = '# Operators\n\n' + '\n'.join(f'### op{i}\n- Definition: op{i}(x) orders observations.\n' for i in range(10))
        metadata = dict(content_hash=hashlib.sha256(body.encode()).hexdigest(), captured_at='2026-10-13T00:00:00Z',
                        source_type='platform_learn_material', source_family='raw/platform/operators')
        source = self.root / 'raw/platform/operators.md'
        source.write_text(render_front_matter(metadata)+body, encoding='utf-8')
        row = dict(metadata, path='raw/platform/operators.md')
        (self.root/'machine/source_index.jsonl').write_text(json.dumps(row)+'\n')
        ref = dict(source_path=row['path'], sha256=row['content_hash'], capture_date='2026-10-13', kind='hypothesis', experiment_refs=[])
        proposal = dict(trigger_id='t', mechanism_id='m', condition_id='c', record=dict(operator='op0', family='normalizer', semantic_version=2,
            semantic_status='reviewed', evidence_refs=[ref], conditional_uses=[dict(conditions='Comparable observations.',
            purpose='Test relative ordering.', failure_risks=['Noise.'], evidence_refs=[ref])]))
        with patch('wqb.semantic_compilation.run_ai_checkpoint', return_value=dict(status='completed', summary='Hypothesis only.',
            proposals=dict(operators=[proposal], templates=[]))):
            result = compiler.compile_semantic_knowledge_command(self.root, dict(executor_argv=['fake']))
        self.assertEqual(result['status'], 'completed', result)
        manifest = json.loads((Path(result['job'])/'run_manifest.json').read_text())
        selected = manifest['source_index'][row['path']]['target_ids']
        self.assertEqual(selected, ['op0', 'op1', 'op2'])
        self.assertTrue(result['coverage']['partial'])
        self.assertEqual(result['release']['manifest']['source_refs'][0]['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertNotEqual(result['release']['manifest']['source_refs'][0]['sha256'], row['content_hash'])

    def test_existing_knowledge_panel_exposes_semantic_start_and_cancel(self):
        from wqb.console_server import _render_data_coverage_panel
        html = _render_data_coverage_panel(dict(semantic_compile=dict(status='running', job_id='abc')))
        self.assertIn('compile-semantic-knowledge', html)
        self.assertIn('cancel-semantic-knowledge', html)
        self.assertNotIn('workflow-continue', html)

    def test_knowledge_panel_reports_remaining_operator_and_research_coverage(self):
        from wqb.console_server import _render_data_coverage_panel
        html = _render_data_coverage_panel(dict(semantic_compile=dict(status='completed', coverage=dict(
            indexed_target_count=110, covered_target_count=3, remaining_target_count=107, remaining_research_source_count=2))))
        self.assertIn('107', html)
        self.assertIn('Research sources remaining: 2', html)

    def test_console_cancel_preserves_already_committed_explanation(self):
        from wqb.console_server import run_console_action
        first = self.invoke()
        paths = default_console_paths(self.root, Path(self.tmp.name)/'runs')
        result = run_console_action(paths, dict(action='cancel-semantic-knowledge', semantic_job_id=Path(first['job']).name))
        self.assertFalse(result.metadata['cancellation']['cancelled'])
        self.assertIn('already completed', result.status_message)

    def test_cancel_during_worker_prevents_publication(self):
        job = self.root/'machine/semantic_jobs/test'
        job.mkdir(parents=True)
        def cancel(*args, **kwargs):
            """Input: worker args. Output: validated proposal dict. Simulate user cancellation during a worker."""
            (job/'control.json').write_text('{"cancelled":true}')
            return self.result
        with patch('wqb.semantic_compilation.prepare_semantic_job', return_value=job), patch(
            'wqb.semantic_compilation.compile_semantic_proposals', side_effect=cancel):
            result = compiler.compile_semantic_knowledge_command(self.root, dict(source_refs=[], executor_argv=['fake']))
        self.assertEqual(result['status'], 'cancelled')
        self.assertIsNone(read_semantic_release(self.root)['release_id'])

    def test_cancel_ack_after_staging_prevents_pointer_commit(self):
        from wqb.semantic_publication import stage_semantic_release
        from wqb.console_jobs import cancel_semantic_job
        staged, proceed = threading.Event(), threading.Event()
        outcome = []
        def pause_after_stage(*args):
            """Input: publisher stage args. Output: immutable receipt dict. Pause outside the short commit lock."""
            receipt = stage_semantic_release(*args)
            staged.set()
            if not proceed.wait(5):
                raise RuntimeError('test barrier expired')
            return receipt
        with patch('wqb.semantic_publication.stage_semantic_release', side_effect=pause_after_stage):
            thread = threading.Thread(target=lambda: outcome.append(self.invoke()))
            thread.start()
            try:
                self.assertTrue(staged.wait(5))
                ack = cancel_semantic_job(self.root, 'test')
                self.assertTrue(ack['cancelled'])
            finally:
                proceed.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome[0]['status'], 'cancelled', outcome)
        self.assertIsNone(read_semantic_release(self.root)['release_id'])

    def test_cancel_during_commit_waits_and_reports_already_completed(self):
        from wqb.semantic_publication import stage_semantic_release, read_semantic_release as read_release
        from wqb.console_jobs import cancel_semantic_job
        staged, committing, proceed, cancel_started, cancel_done = [threading.Event() for _ in range(5)]
        outcome, cancellations = [], []
        def stage(*args):
            """Input: stage args. Output: immutable receipt dict. Identify the post-stage commit boundary."""
            receipt = stage_semantic_release(*args)
            staged.set()
            return receipt
        def read(root):
            """Input: vault Path. Output: receipt dict. Pause the writer after its last cancellation check."""
            if staged.is_set() and threading.current_thread().name == 'semantic-writer' and not committing.is_set():
                committing.set()
                if not proceed.wait(5):
                    raise RuntimeError('test commit barrier expired')
            return read_release(root)
        def cancel():
            """Input: none. Output: None. Record cancellation acknowledgement from a competing user request."""
            cancel_started.set()
            cancellations.append(cancel_semantic_job(self.root, 'test'))
            cancel_done.set()
        with patch('wqb.semantic_publication.stage_semantic_release', side_effect=stage), patch(
            'wqb.semantic_publication.read_semantic_release', side_effect=read):
            writer = threading.Thread(name='semantic-writer', target=lambda: outcome.append(self.invoke()))
            writer.start()
            self.assertTrue(committing.wait(5))
            canceller = threading.Thread(target=cancel)
            canceller.start()
            try:
                self.assertTrue(cancel_started.wait(5))
                self.assertFalse(cancel_done.wait(0.15), 'cancel acknowledged while pointer commit still pending')
            finally:
                proceed.set()
                writer.join(5)
                canceller.join(5)
        self.assertFalse(writer.is_alive() or canceller.is_alive())
        self.assertEqual(outcome[0]['status'], 'completed', outcome)
        self.assertFalse(cancellations[0]['cancelled'], cancellations)

    def test_same_hypothesis_version_cannot_acquire_different_template_id(self):
        result = self.invoke(dict(self.result, validated_templates=[dict(self.old, template_id='new', skeleton='-rank({field})')]))
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('hypothesis', result['error'])

    def test_missing_index_never_calls_worker(self):
        with patch('wqb.semantic_compilation.compile_semantic_proposals') as worker:
            result = compiler.compile_semantic_knowledge_command(self.root, {})
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('source', result['error'])
        worker.assert_not_called()

    def test_malformed_index_persists_blocker_instead_of_crashing(self):
        (self.root/'machine/source_index.jsonl').write_text('[]\n')
        result = compiler.compile_semantic_knowledge_command(self.root, {})
        self.assertEqual(result['status'], 'blocked', result)
        self.assertIn('object', result['error'])

    def test_unsupported_research_aggregate_remains_visible_not_measured(self):
        self.captured_operators(1)
        rows = [json.loads(line) for line in (self.root/'machine/source_index.jsonl').read_text().splitlines()]
        rows.append(dict(path='raw/research/aggregate.jsonl', content_hash='unknown', captured_at='2026-10-14T00:00:00Z',
                         source_type='workflow_research_record', source_family='raw/research'))
        coverage = {}
        selected = compiler._select_semantic_sources(self.root, rows, coverage)
        self.assertEqual(len(selected), 1)
        self.assertEqual(coverage['unsupported_research_source_count'], 1)
        self.assertIn('unmeasured', json.dumps(coverage))

    def test_malformed_console_receipts_are_blocked_or_failed(self):
        from wqb import console_jobs, console_state
        job = self.root/'machine/semantic_jobs/bad'
        job.mkdir(parents=True)
        (job/'command_result.json').write_text('[]')
        self.assertEqual(console_state._latest_semantic_compile(self.root)['status'], 'blocked')
        process = console_jobs.create_job(Path(self.tmp.name)/'jobs', 'compile-semantic-knowledge', ['fake'], self.root)
        Path(process.stdout_path).write_text('[]')
        self.assertEqual(console_jobs._finalize_process_result(process, 0).status, 'failed')

    def test_console_terminal_receipt_retries_transient_windows_sharing_failure(self):
        from wqb import console_jobs
        process = console_jobs.create_job(Path(self.tmp.name)/'jobs', 'compile-semantic-knowledge', ['fake'], self.root)
        Path(process.stdout_path).write_text('{"status":"completed"}')
        original = console_jobs.os.replace
        attempts = []
        def replace(source, target):
            """Input: temporary/target Paths. Output: None. Reproduce a transient Windows reader sharing violation."""
            attempts.append(target)
            if len(attempts) == 1:
                raise PermissionError('Windows sharing violation')
            return original(source, target)
        with patch('wqb.console_jobs.os.replace', side_effect=replace):
            final = console_jobs._finalize_process_result(process, 0)
        self.assertEqual(final.status, 'completed')
        self.assertEqual(len(attempts), 2)
        self.assertEqual(json.loads((Path(final.job_dir)/'job.json').read_text())['status'], 'completed')

    def test_console_semantic_action_is_async_and_cancel_is_not_research_stop(self):
        from wqb.console_server import run_console_action
        paths = default_console_paths(self.root, Path(self.tmp.name)/'runs')
        with patch('wqb.console_server.start_job_async', side_effect=lambda job, **kw: job) as start:
            job = run_console_action(paths, dict(action='compile-semantic-knowledge'))
        self.assertEqual(job.action, 'compile-semantic-knowledge')
        self.assertEqual(start.call_count, 1)
        knowledge_job = self.root/'machine/semantic_jobs/test'
        knowledge_job.mkdir(parents=True)
        stopped = run_console_action(paths, dict(action='cancel-semantic-knowledge', semantic_job_id='test'))
        self.assertEqual(stopped.status, 'completed')
        self.assertFalse((paths.runs_root/'runtime_control.json').exists())

    def test_raw_operator_writer_refuses_active_generation(self):
        self.assertEqual(self.invoke()['status'], 'completed')
        from wqb.operator_semantics import write_operator_semantics_jsonl
        path = Path(read_semantic_release(self.root)['paths']['operator_ledger'])
        with self.assertRaisesRegex(ValueError, 'semantic'):
            write_operator_semantics_jsonl(path, [])

    def test_paired_read_detects_resource_change_before_decode(self):
        from wqb import semantic_publication
        original = semantic_publication.read_semantic_release
        def change(root):
            """Input: vault Path. Output: stale receipt dict. Simulate a replacement after acquiring a receipt."""
            receipt = original(root)
            Path(receipt['paths']['operator_ledger']).write_text('{"operator":"changed"}\n')
            return receipt
        with patch('wqb.semantic_publication.read_semantic_release', side_effect=change):
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                compiler.read_semantic_rows(self.root)

    def test_generated_research_record_is_incremental_hypothesis_material(self):
        from wqb.research_record import empty_research_record, record_alpha_result, sync_research_record_to_raw
        record = record_alpha_result(empty_research_record('run1', 'Power Pool'), dict(alpha_id='alpha1',
            expression_hash='hash1', hard_pass=False, benchmark_label='near_miss', failed=['prod_correlation']))
        source = sync_research_record_to_raw(record, self.root/'raw')
        summary = compiler.compile_research_records(self.root)
        self.assertEqual(summary['record_count'], 1)
        rows = [json.loads(line) for line in (self.root/'machine/source_index.jsonl').read_text().splitlines()]
        row = next(row for row in rows if row['path'] == source.relative_to(self.root).as_posix())
        ref = dict(source_path=row['path'], sha256=row['content_hash'], capture_date=row['captured_at'][:10],
            kind='hypothesis', experiment_refs=[])
        proposal = dict(trigger_id='research', mechanism_id='m', condition_id='c', record=dict(operator='rank', family='normalizer',
            semantic_version=2, evidence_refs=[ref], conditional_uses=[dict(conditions='Comparable observations.',
                purpose='Test ordering after the recorded failure.', failure_risks=['Correlation.'], evidence_refs=[ref])]))
        with patch('wqb.semantic_compilation.run_ai_checkpoint', return_value=dict(status='completed', summary='Unverified lesson.',
            proposals=dict(operators=[proposal], templates=[]))) as worker:
            first = compiler.compile_semantic_knowledge_command(self.root, dict(source_refs=[row], executor_argv=['fake']))
            second = compiler.compile_semantic_knowledge_command(self.root, dict(source_refs=[row], executor_argv=['fake']))
        self.assertEqual(first['status'], 'completed', first)
        self.assertEqual(first['release']['release_id'], second['release']['release_id'])
        self.assertEqual(worker.call_count, 1)
        _, operators, _ = compiler.read_semantic_rows(self.root)
        self.assertEqual(operators[0]['evidence_refs'][0]['kind'], 'hypothesis')

    def test_default_semantic_flow_selects_new_indexed_research_without_manual_refs(self):
        from wqb.research_record import empty_research_record, sync_research_record_to_raw
        sync_research_record_to_raw(empty_research_record('newrun', 'Power Pool'), self.root/'raw')
        compiler.compile_research_records(self.root)
        row = json.loads((self.root/'machine/source_index.jsonl').read_text().splitlines()[0])
        with patch('wqb.semantic_compilation.run_ai_checkpoint', return_value=self.proposals_for_targets(row, ['rank'])) as worker:
            first = compiler.compile_semantic_knowledge_command(self.root, dict(executor_argv=['fake']))
            second = compiler.compile_semantic_knowledge_command(self.root, dict(executor_argv=['fake']))
        self.assertEqual(first['status'], 'completed', first)
        self.assertEqual(second['cache_status'], 'hit', second)
        self.assertEqual(worker.call_count, 1)
        self.assertEqual(first['coverage']['remaining_research_source_count'], 0)
        _, operators, _ = compiler.read_semantic_rows(self.root)
        self.assertEqual(operators[0]['evidence_refs'][0]['kind'], 'hypothesis')

    def test_dirty_legacy_structure_blocks_without_changing_pointer_or_deleting(self):
        self.assertEqual(self.invoke()['status'], 'completed')
        before = (self.root/'machine/semantic_release.json').read_bytes()
        dirty = self.root/'wiki/20_semantics/old.jsonl'
        dirty.parent.mkdir()
        dirty.write_text('{"old":true}\n')
        result = self.invoke(_job_name='dirty', generated_at='2026-10-14T00:00:00Z')
        self.assertEqual(result['status'], 'blocked', result)
        self.assertIn('legacy_active_path', result['error'])
        self.assertEqual((self.root/'machine/semantic_release.json').read_bytes(), before)
        self.assertTrue(dirty.exists())

    def test_invalid_existing_wiki_link_blocks_publication(self):
        (self.root/'wiki/50_engineering_lessons.md').write_text('# Lessons\n[Missing](../raw/no-such-evidence.md)\n')
        result = self.invoke()
        self.assertEqual(result['status'], 'blocked', result)
        self.assertIn('wiki link', result['error'])
        self.assertIsNone(read_semantic_release(self.root)['release_id'])

    def test_partial_publication_keeps_retained_source_provenance(self):
        old_ref = dict(source_path=self.ref['path'], sha256=self.ref['sha256'], capture_date='2026-10-13', kind='hypothesis', experiment_refs=[])
        first = self.invoke(dict(self.result, validated_operators=[dict(operator='ts_delta', semantic_version=2, evidence_refs=[old_ref])]))
        self.assertEqual(first['status'], 'completed', first)
        second_source = self.root/'raw/platform/second.txt'
        second_source.write_text('A different source.')
        second_ref = dict(path='raw/platform/second.txt', sha256=hashlib.sha256(second_source.read_bytes()).hexdigest())
        second = self.invoke(dict(self.result, source_refs=[second_ref], validated_operators=[dict(operator='ts_mean')]), _job_name='second')
        self.assertEqual(second['status'], 'completed', second)
        self.assertEqual(second['release']['manifest']['source_refs'], [self.ref, second_ref])

    def test_changed_retained_source_is_explicit_blocker(self):
        old_ref = dict(source_path=self.ref['path'], sha256=self.ref['sha256'], capture_date='2026-10-13', kind='hypothesis', experiment_refs=[])
        self.assertEqual(self.invoke(dict(self.result, validated_operators=[dict(operator='ts_delta', semantic_version=2, evidence_refs=[old_ref])]))['status'], 'completed')
        before = (self.root/'machine/semantic_release.json').read_bytes()
        (self.root/self.ref['path']).write_text('Changed definition.')
        changed = dict(self.ref, sha256=hashlib.sha256((self.root/self.ref['path']).read_bytes()).hexdigest())
        result = self.invoke(dict(self.result, source_refs=[changed], validated_operators=[dict(operator='ts_mean')]), _job_name='changed')
        self.assertEqual(result['status'], 'blocked', result)
        self.assertIn('retained', result['error'])
        self.assertEqual((self.root/'machine/semantic_release.json').read_bytes(), before)

    def test_wiki_links_each_use_evidence_and_valid_failure_case(self):
        from wqb.knowledge_experience_compile import render_semantic_wiki_materials
        ref = dict(source_path=self.ref['path'], kind='hypothesis', experiment_refs=[])
        proposals = dict(self.result, validated_operators=[dict(operator='rank', conditional_uses=[dict(
            conditions='Comparable observations.', purpose='Ordering.', failure_risks=['Noise.'], evidence_refs=[ref])])])
        page = render_semantic_wiki_materials(proposals, '2026-10-13T00:00:00Z')['wiki/30_template_and_operator_patterns.md']
        evidence = next(line for line in page.splitlines() if line.startswith('- Evidence:'))
        self.assertIn('[hypothesis: definition.txt](../raw/platform/definition.txt)', evidence)

    def test_wiki_does_not_turn_model_text_into_links_or_measured_claims(self):
        from wqb.knowledge_experience_compile import render_semantic_wiki_materials
        proposals = dict(self.result, validated_operators=[dict(operator='rank', conditional_uses=[dict(
            conditions='[bad](https://example.com)', purpose='Relative order.', failure_risks=['Noise.'], evidence_refs=[])])])
        pages = render_semantic_wiki_materials(proposals, '2026-10-13T00:00:00Z')
        text = pages['wiki/30_template_and_operator_patterns.md']
        self.assertNotIn('[bad](https://example.com)', text)
        self.assertIn('Evidence: unverified', text)

    def research_lesson_source(self, body='# Lesson\nA recorded failure suggests a bounded ordering hypothesis.\n', platform=False):
        """Input: Markdown body str. Output: indexed row dict. Create a second independently hashed research source."""
        from wqb.knowledge_contracts import render_front_matter
        row = dict(path='raw/research/lesson.md', content_hash=hashlib.sha256(body.encode()).hexdigest(),
                   captured_at='2026-10-14T00:00:00Z', source_type='workflow_research_record', source_family='raw/research')
        if platform:
            row.update(path='raw/platform/operators/alternate.md', source_type='platform_learn_material', source_family='raw/platform/operators')
        path = self.root/row['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_front_matter(row)+body, encoding='utf-8')
        return row

    def test_real_task3_incremental_operator_keeps_uses_definition_and_source_closure(self):
        platform = self.captured_operators(1)
        first_output = self.proposals_for_targets(platform, ['op0'])
        record = first_output['proposals']['operators'][0]['record']
        record['raw_definition'] = 'op0(x) orders observations.'
        record['evidence_refs'] = [dict(record['evidence_refs'][0], kind='documented')]
        with patch('wqb.semantic_compilation.run_ai_checkpoint', return_value=first_output):
            first = compiler.compile_semantic_knowledge_command(self.root, dict(executor_argv=['fake']))
        self.assertEqual(first['status'], 'completed', first)
        lesson = self.research_lesson_source()
        second_output = self.proposals_for_targets(lesson, ['op0'])
        second_output['proposals']['operators'][0]['record']['conditional_uses'][0]['conditions'] = 'After the recorded failure.'
        with patch('wqb.semantic_compilation.run_ai_checkpoint', return_value=second_output):
            second = compiler.compile_semantic_knowledge_command(self.root, dict(source_refs=[lesson], executor_argv=['fake']))
        self.assertEqual(second['status'], 'completed', second)
        _, rows, _ = compiler.read_semantic_rows(self.root)
        operator = next(row for row in rows if row['operator'] == 'op0')
        self.assertEqual(len(operator['conditional_uses']), 2)
        self.assertEqual(operator['raw_definition'], record['raw_definition'])
        expected = {platform['path'], lesson['path']}
        self.assertEqual({ref['source_path'] for ref in operator['evidence_refs']}, expected)
        self.assertEqual({ref['path'] for ref in second['release']['manifest']['source_refs']}, expected)
        wiki = (self.root/'wiki/30_template_and_operator_patterns.md').read_text()
        self.assertIn('../raw/platform/operators/operators.md', wiki)
        self.assertIn('../raw/research/lesson.md', wiki)

    def test_real_task3_conflicting_operator_definition_blocks_without_replacing_active(self):
        platform = self.captured_operators(1)
        output = self.proposals_for_targets(platform, ['op0'])
        record = output['proposals']['operators'][0]['record']
        record['raw_definition'] = 'op0(x) orders observations.'
        record['evidence_refs'] = [dict(record['evidence_refs'][0], kind='documented')]
        with patch('wqb.semantic_compilation.run_ai_checkpoint', return_value=output):
            first = compiler.compile_semantic_knowledge_command(self.root, dict(source_refs=[platform], executor_argv=['fake']))
        self.assertEqual(first['status'], 'completed', first)
        lesson = self.research_lesson_source('# Lesson\nop0(x) reverses observations.\n', platform=True)
        conflicting = self.proposals_for_targets(lesson, ['op0'])
        incoming = conflicting['proposals']['operators'][0]['record']
        incoming['raw_definition'] = 'op0(x) reverses observations.'
        incoming['evidence_refs'] = [dict(incoming['evidence_refs'][0], kind='documented')]
        with patch('wqb.semantic_compilation.run_ai_checkpoint', return_value=conflicting):
            result = compiler.compile_semantic_knowledge_command(self.root, dict(source_refs=[lesson], executor_argv=['fake']))
        self.assertEqual(result['status'], 'blocked', result)
        self.assertIn('conflicting operator', result['error'])
        self.assertEqual(read_semantic_release(self.root)['release_id'], first['release']['release_id'])

    def test_completed_older_job_replay_repairs_only_active_wiki(self):
        first = self.invoke()
        second = self.invoke(dict(self.result, validated_operators=[dict(operator='ts_mean')]), _job_name='second')
        self.assertNotEqual(first['release']['release_id'], second['release']['release_id'])
        pointer = (self.root/'machine/semantic_release.json').read_bytes()
        page = self.root/'wiki/30_template_and_operator_patterns.md'
        expected = page.read_bytes()
        page.write_text('# Drifted wiki\n')
        result = self.invoke()
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(page.read_bytes(), expected)
        self.assertEqual((self.root/'machine/semantic_release.json').read_bytes(), pointer)
        self.assertEqual(result['active_release']['release_id'], second['release']['release_id'])

    def test_completed_wiki_repair_rechecks_active_under_publisher_lock(self):
        from wqb import semantic_publication as publication
        first = self.invoke()
        staged = publication.stage_semantic_release(self.root, dict(self.result, validated_templates=[self.old],
            wiki_materials={'wiki/30_template_and_operator_patterns.md': '# New active wiki\n'}), '2026-10-14T00:00:00Z')
        acquire = publication._acquire_lock
        switched = []
        def switch_before_acquire(root):
            """Input: vault Path. Output: lock handle. Simulate another publisher winning before replay acquires the commit lock."""
            if not switched:
                switched.append(True)
                publication.publish_semantic_release(root, staged)
            return acquire(root)
        with patch('wqb.semantic_publication._acquire_lock', side_effect=switch_before_acquire):
            result = self.invoke()
        self.assertEqual(result['status'], 'blocked', result)
        self.assertIn('changed before wiki repair', result['error'])
        self.assertEqual(read_semantic_release(self.root)['release_id'], staged['release_id'])
        self.assertIn('# New active wiki', (self.root/'wiki/30_template_and_operator_patterns.md').read_text())
        resumed = self.invoke()
        self.assertEqual(resumed['status'], 'completed', resumed)
        self.assertEqual(resumed['release']['release_id'], first['release']['release_id'])
        self.assertEqual(resumed['active_release']['release_id'], staged['release_id'])

    def test_typed_operator_definition_merge_preserves_and_rejects_conflict(self):
        definition = dict(description='Order observations.', input_types=['MATRIX'], output_type='MATRIX', parameters=[], evidence_refs=[])
        old = dict(operator='rank', definition=definition, raw_definition='rank(x)', family='normalizer',
                   conditional_uses=[dict(conditions='Original')], evidence_refs=[], workflow_uses=['Cross-sectional ordering'])
        merged = compiler._merge_semantic_rows([old], [dict(operator='rank', definition=None, raw_definition='',
            conditional_uses=[dict(conditions='Research')], evidence_refs=[], workflow_uses=[])], 'operator')[0]
        self.assertEqual(merged['definition'], definition)
        self.assertEqual(merged['raw_definition'], 'rank(x)')
        self.assertEqual(merged['workflow_uses'], old['workflow_uses'])
        with self.assertRaisesRegex(ValueError, 'conflicting operator typed'):
            compiler._merge_semantic_rows([old], [dict(operator='rank', definition=dict(definition, output_type='VECTOR'))], 'operator')

    def test_real_task3_cancelled_default_replay_exposes_terminal_blocker_and_dedup_notice(self):
        from wqb.console_jobs import cancel_semantic_job
        row = self.captured_operators(5)
        def cancel(directory, *args, **kwargs):
            """Input: checkpoint directory/args. Output: cancelled checkpoint dict. Persist cancellation on its prepared root job."""
            root_job = next(path.parent for path in (self.root/'machine/semantic_jobs').glob('*/command_result.json'))
            cancel_semantic_job(self.root, root_job.name)
            return dict(status='cancelled', error='User cancelled knowledge compile')
        with patch('wqb.semantic_compilation.run_ai_checkpoint', side_effect=cancel) as worker:
            first = compiler.compile_semantic_knowledge_command(self.root, dict(executor_argv=['fake']))
            second = compiler.compile_semantic_knowledge_command(self.root, dict(executor_argv=['fake']))
            third = compiler.compile_semantic_knowledge_command(self.root, dict(executor_argv=['fake']))
        self.assertEqual(first['status'], 'cancelled', first)
        self.assertEqual(second['status'], 'blocked', second)
        self.assertIn('cancelled content key', second['error'])
        self.assertIn('maintenance', second['next_action'])
        self.assertNotEqual(second['notification']['status'], 'not_needed')
        self.assertEqual(second['notification'], third['notification'])
        self.assertEqual(second['coverage']['remaining_target_count'], 5)
        self.assertEqual(worker.call_count, 1)
        self.assertTrue(json.loads((Path(first['job'])/'control.json').read_text())['cancelled'])
