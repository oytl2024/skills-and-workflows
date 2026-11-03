"""Prepare-only K4 tests using isolated local vaults, never model or live resources."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wqb.full_semantic_compile import prepare_full_semantic_compile


class FullSemanticInventoryTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: temporary vault Path with automatic cleanup."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, path, value):
        """Input: relative str and str/object. Output: Path; write a fixture only."""
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8', newline='\n')
        return target

    def source(self, path, text):
        """Input: relative str/text str. Output: registered source dict with exact digest."""
        self.write(path, text)
        row = dict(path=path, content_hash=hashlib.sha256(text.encode()).hexdigest(),
                   captured_at='2026-10-23T00:00:00Z', source_type='platform',
                   source_family=str(Path(path).parent).replace('\\', '/'))
        self.write('machine/source_index.jsonl', json.dumps(row) + '\n')
        return row

    def inventory(self, plan):
        """Input: plan dict. Output: inventory list decoded from hash-bound JSONL."""
        raw = (self.root / plan['inventory_ref']['path']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), plan['inventory_ref']['sha256'])
        return [json.loads(line) for line in raw.splitlines()]

    def field(self, name='price', universe='TOP3000', description='Closing price'):
        """Input: identity/scope/description strings. Output: raw capture wrapper dict."""
        return dict(scope=dict(region='USA', delay=1, universe=universe, instrument_type='EQUITY'),
                    data_set=dict(id='prices', description='Daily prices'),
                    field=dict(id=name, type='MATRIX', description=description, coverage=0.8))

    def test_scope_union_meaning_dedup_and_zero_authority(self):
        captures = [self.field(), self.field(universe='TOP1000')]
        source = self.source('raw/platform/data_fields/day/data_fields.jsonl',
                             ''.join(json.dumps(row) + '\n' for row in captures))
        self.write('machine/data_ledger.jsonl', json.dumps(dict(dataset_id='prices', field_id='price',
            field_type='MATRIX', field_description='Closing price', region='USA', delay=1,
            universe='TOP3000', instrument_type='EQUITY', coverage=0.8, source_paths=[source['path']])) + '\n')
        with patch('wqb.semantic_compilation.run_ai_checkpoint', side_effect=AssertionError('model forbidden')):
            plan = prepare_full_semantic_compile(self.root, {})
        rows = self.inventory(plan)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]['scopes']), 2)
        self.assertEqual(len(rows[0]['occurrences']), 3)
        self.assertTrue(rows[0]['source_validated'])
        self.assertFalse(rows[0]['eligibility']['research_eligible'])
        self.assertEqual(plan['budget']['model_call_budget'], 0)
        self.assertEqual(plan['model_calls'], 0)
        self.assertFalse(plan['publication_authorized'])
        self.assertEqual(plan['root'], str(self.root.resolve()))
        self.assertEqual(sum(len(job['target_ids']) for job in plan['jobs']), 1)

    def test_bad_indexed_operators_are_retained_without_aborting_other_sources(self):
        bad = self.source('raw/platform/learn/old/operators.md', '### old_op\nOld source\n')
        bad['content_hash'] = '0' * 64
        good_path = 'raw/platform/learn/new/operators.md'
        good_text = '### new_op\n- Definition: new_op(x)\n- Description: New operation.\n'
        self.write(good_path, good_text)
        good = dict(bad, path=good_path, content_hash=hashlib.sha256(good_text.encode()).hexdigest())
        self.write('machine/source_index.jsonl', '\n'.join(json.dumps(row) for row in [bad, good]))
        self.write('machine/operator_ledger.jsonl', json.dumps(dict(operator='canonical_only', family='other')))
        plan = prepare_full_semantic_compile(self.root, {})
        rows = {row['identity']['operator']: row for row in self.inventory(plan)}
        self.assertEqual(set(rows), {'old_op', 'new_op', 'canonical_only'})
        self.assertFalse(rows['old_op']['source_validated'])
        self.assertEqual(rows['old_op']['status'], 'blocked')
        self.assertTrue(rows['new_op']['source_validated'])
        self.assertTrue(any(item['path'] == bad['path'] for item in plan['diagnostics']))

    def test_content_keys_reuse_immutable_files_and_invalidate_on_rules_or_source(self):
        path = 'raw/platform/learn/day/operators.md'
        self.source(path, '### rank\n- Description: Cross-sectional rank.\n')
        first = prepare_full_semantic_compile(self.root, {})
        before = {p: p.stat().st_mtime_ns for p in (self.root / 'machine/semantic_jobs').rglob('*') if p.is_file()}
        second = prepare_full_semantic_compile(self.root, {})
        self.assertEqual(first['content_key'], second['content_key'])
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})
        self.assertEqual(second['estimates']['cached_jobs'], len(second['jobs']))
        changed = prepare_full_semantic_compile(self.root, dict(rules_version='changed'))
        self.assertNotEqual(changed['content_key'], first['content_key'])
        self.assertNotEqual(changed['jobs'][0]['job_id'], first['jobs'][0]['job_id'])
        self.source(path, '### rank\n- Description: Changed literal description.\n')
        self.assertNotEqual(prepare_full_semantic_compile(self.root, {})['content_key'], first['content_key'])

    def test_large_raw_inventory_has_no_trust_or_raised_material_bound(self):
        from wqb.semantic_compilation import MAX_SOURCE_BYTES
        row = self.field()
        text = (json.dumps(row) + '\n') * (MAX_SOURCE_BYTES // len(json.dumps(row)) + 1)
        self.source('raw/platform/data_fields/day/data_fields.jsonl', text)
        plan = prepare_full_semantic_compile(self.root, {})
        target = self.inventory(plan)[0]
        self.assertFalse(target['source_validated'])
        self.assertEqual(target['status'], 'blocked')
        self.assertEqual(plan['jobs'], [])
        self.assertTrue(any('bound' in str(gap) for gap in plan['diagnostics']))

    def test_sources_verified_and_parsed_once_per_scan(self):
        import wqb.full_semantic_compile as module
        self.source('raw/platform/data_fields/day/data_fields.jsonl',
                    ''.join(json.dumps(self.field('f' + str(i))) + '\n' for i in range(35)))
        with patch.object(module, '_material', wraps=module._material) as material:
            plan = prepare_full_semantic_compile(self.root, {})
        self.assertEqual(material.call_count, 1)
        self.assertEqual(len(self.inventory(plan)), 35)
        self.assertLess(len(plan['jobs']), 35)
        assigned = [target for job in plan['jobs'] for target in job['target_ids']]
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertEqual(len(assigned), 35)

    def test_complete_material_not_truncated_and_all_targets_accounted(self):
        text = '### small\nComplete.\n### huge\n' + 'x' * 8000 + '\n'
        self.source('raw/platform/learn/day/operators.md', text)
        plan = prepare_full_semantic_compile(self.root, {})
        rows = {row['identity']['operator']: row for row in self.inventory(plan)}
        self.assertEqual(rows['huge']['status'], 'blocked')
        self.assertEqual(rows['small']['status'], 'prepared')
        self.assertEqual(plan['coverage']['target_count'], 2)
        for job in plan['jobs']:
            manifest = json.loads((self.root / job['path']).read_bytes())
            self.assertLessEqual(manifest['input_bytes'], 11000)
            self.assertEqual(manifest['target_ids'], job['target_ids'])
            self.assertEqual(manifest['output_contract']['exact_target_ids'], job['target_ids'])

    def test_sensitive_and_escape_sources_do_not_read_or_schedule(self):
        rows = [dict(path=path, target_ids=['blocked_op'], content_hash='0' * 64,
                     captured_at='2026-10-23T00:00:00Z', source_type='platform', source_family='raw/platform')
                for path in ['../outside.md', 'raw/platform/credentials/data.md']]
        self.write('machine/source_index.jsonl', '\n'.join(json.dumps(row) for row in rows))
        plan = prepare_full_semantic_compile(self.root, {})
        self.assertEqual(plan['jobs'], [])
        self.assertEqual(self.inventory(plan)[0]['identity']['operator'], 'blocked_op')
        self.assertEqual(len(plan['diagnostics']), 2)

    def test_invalid_budget_is_rejected_before_writes(self):
        for value in [-1, True, 1.5, '1']:
            with self.assertRaises(ValueError):
                prepare_full_semantic_compile(self.root, dict(model_call_budget=value))
        self.assertFalse((self.root / 'machine/semantic_jobs').exists())

    def test_unverified_scope_is_never_inherited_from_verified_scope(self):
        self.source('raw/platform/data_fields/day/data_fields.jsonl', json.dumps(self.field()) + '\n')
        self.write('machine/data_ledger.jsonl', json.dumps(dict(dataset_id='prices', field_id='price',
            region='USA', delay=1, universe='TOP1000', field_description='Different meaning', source_paths=[])))
        target = self.inventory(prepare_full_semantic_compile(self.root, {}))[0]
        self.assertEqual([s['universe'] for s in target['source_validated_scopes']], ['TOP3000'])
        self.assertTrue(any(gap['code'] == 'unverified_occurrences' for gap in target['gaps']))
        self.assertTrue(any(gap['code'] == 'conflicting_literal_meanings' for gap in target['gaps']))

    def test_certified_extract_supplies_material_without_repairing_large_original(self):
        from wqb.knowledge_contracts import extract_field_source_subset
        from wqb.semantic_compilation import MAX_SOURCE_BYTES
        row = dict(self.field(), capture_generation_id='fixture', generated_at='2026-10-23T00:00:00Z',
                   endpoint='/data-fields')
        path = 'raw/platform/data_fields/2026-10-23/data_fields.jsonl'
        self.write(path, json.dumps(row) + '\n' + '\n' * MAX_SOURCE_BYTES)
        self.write('raw/platform/data_fields/2026-10-23/manifest.json', dict(generated_at=row['generated_at'],
            capture_generation_id='fixture', scope=row['scope'], certification_status='complete', field_count=1, error_count=0))
        extract_field_source_subset(self.root, path,
            [dict(dataset_id='prices', field_id='price', scope=row['scope'])])
        before = (self.root / path).read_bytes()
        target = self.inventory(prepare_full_semantic_compile(self.root, {}))[0]
        self.assertTrue(target['source_validated'])
        self.assertEqual(target['status'], 'prepared')
        self.assertEqual((self.root / path).read_bytes(), before)

    def test_tampered_prepared_input_is_not_overwritten_or_reused(self):
        self.source('raw/platform/learn/day/operators.md', '### rank\nRank.\n')
        plan = prepare_full_semantic_compile(self.root, {})
        manifest = json.loads((self.root / plan['jobs'][0]['path']).read_bytes())
        path = self.root / manifest['input_ref']['path']
        path.write_bytes(b'{"tampered":true}')
        with self.assertRaises(ValueError):
            prepare_full_semantic_compile(self.root, {})
        self.assertEqual(path.read_bytes(), b'{"tampered":true}')

    def test_active_canonical_and_raw_operator_union(self):
        from wqb.semantic_publication import stage_semantic_release
        (self.root / 'wiki').mkdir()
        staged = stage_semantic_release(self.root, dict(validated_operators=[dict(operator='active_only')],
            validated_templates=[], source_refs=[], wiki_materials={}), '2026-10-23T00:00:00Z')
        self.write('machine/semantic_release.json', {key: staged[key]
                   for key in ('schema_version', 'release_id', 'manifest_sha256')})
        self.write('machine/operator_ledger.jsonl', json.dumps(dict(operator='canonical_only')))
        self.source('raw/platform/learn/day/operators.md', '### raw_only\nRaw.\n')
        rows = self.inventory(prepare_full_semantic_compile(self.root, {}))
        self.assertEqual({r['identity']['operator'] for r in rows}, {'active_only', 'canonical_only', 'raw_only'})
        active = next(r for r in rows if r['identity']['operator'] == 'active_only')
        self.assertEqual(active['occurrences'][0]['origin'], 'active')

    def test_partial_malformed_inventory_is_not_reported_complete(self):
        self.write('raw/platform/data_fields/day/data_fields.jsonl', json.dumps(self.field()) + '\nnot json\n')
        plan = prepare_full_semantic_compile(self.root, {})
        self.assertFalse(plan['coverage']['inventory_complete'])
        self.assertEqual(plan['coverage']['target_count'], 1)

    def test_missing_semantics_are_permitted_and_byte_validation_is_not_freshness(self):
        source = self.source('raw/platform/data_fields/day/data_fields.jsonl',
                             json.dumps(self.field(description='')) + '\n')
        source['captured_at'] = '2000-01-01T00:00:00Z'
        self.write('machine/source_index.jsonl', json.dumps(source))
        plan = prepare_full_semantic_compile(self.root, {})
        target = self.inventory(plan)[0]
        self.assertTrue(target['source_validated'])
        self.assertEqual(target['source_validation_scope'], 'indexed_bytes_only')
        self.assertEqual(target['freshness_status'], 'not_evaluated')
        manifest = json.loads((self.root / plan['jobs'][0]['path']).read_bytes())
        contract = manifest['output_contract']
        self.assertTrue(contract['unresolved_semantics_allowed'])
        self.assertTrue(contract['literal_fact_summary_nullable'])
        self.assertIn('unresolved', contract['allowed_semantic_statuses'])

    def test_unidentified_index_source_blocks_global_prepared_status(self):
        """Input: valid source plus pathless index row. Output: partial plan with explicit omission."""
        row = self.source('raw/platform/learn/day/operators.md', '### rank\nRank.\n')
        self.write('machine/source_index.jsonl', json.dumps(row) + '\n' + json.dumps(dict(contents='unknown source')))
        plan = prepare_full_semantic_compile(self.root, {})
        self.assertFalse(plan['coverage']['inventory_complete'])
        self.assertEqual(plan['status'], 'partial')
        self.assertEqual(plan['coverage']['prepared_targets'], 1)
        self.assertIn('invalid_index', {s['code'] for s in plan['coverage']['unresolved_inventory_sources']})

    def test_invalid_active_release_is_an_unresolved_inventory_source(self):
        """Input: unreadable active release identity. Output: partial inventory even without known targets."""
        self.write('machine/semantic_release.json', '{broken')
        plan = prepare_full_semantic_compile(self.root, {})
        self.assertFalse(plan['coverage']['inventory_complete'])
        self.assertEqual(plan['status'], 'partial')
        self.assertIn('active_release_gap', {s['code'] for s in plan['coverage']['unresolved_inventory_sources']})

    def test_missing_source_without_target_ids_is_an_inventory_omission(self):
        """Input: indexed missing source, no target contract. Output: explicit unresolved source, not empty success."""
        row = dict(path='raw/research/missing.md', content_hash='0' * 64,
                   captured_at='2026-10-23T00:00:00Z', source_type='research', source_family='raw/research')
        self.write('machine/source_index.jsonl', json.dumps(row))
        plan = prepare_full_semantic_compile(self.root, {})
        self.assertFalse(plan['coverage']['inventory_complete'])
        self.assertEqual(plan['status'], 'partial')
        self.assertIn(row['path'], {s['path'] for s in plan['coverage']['unresolved_inventory_sources']})

    def test_oversized_non_jsonl_source_is_an_inventory_omission(self):
        """Input: indexed oversized JSON catalog. Output: no guessed targets and explicit omitted source."""
        from wqb.semantic_compilation import MAX_SOURCE_BYTES
        row = self.source('raw/platform/learn/day/operators.json',
                          json.dumps([dict(operator='unknown', description='x' * MAX_SOURCE_BYTES)]))
        plan = prepare_full_semantic_compile(self.root, {})
        self.assertFalse(plan['coverage']['inventory_complete'])
        self.assertEqual(plan['status'], 'partial')
        self.assertIn(row['path'], {s['path'] for s in plan['coverage']['unresolved_inventory_sources']})

    def test_read_failure_preserves_other_inventory_and_marks_omission(self):
        """Input: one denied source read. Output: partial plan retains independently readable targets."""
        row = self.source('raw/platform/learn/day/operators.md', '### rank\nRank.\n')
        denied = self.write('raw/research/denied.md', '### Conclusion\nEvidence.\n')
        other = dict(row, path='raw/research/denied.md', content_hash=hashlib.sha256(denied.read_bytes()).hexdigest())
        self.write('machine/source_index.jsonl', json.dumps(row) + '\n' + json.dumps(other))
        read_bytes = Path.read_bytes

        def read(path):
            """Input: Path. Output: actual bytes except the explicitly denied fixture source."""
            if path == denied:
                raise PermissionError('fixture read denied')
            return read_bytes(path)

        with patch.object(Path, 'read_bytes', read):
            plan = prepare_full_semantic_compile(self.root, {})
        self.assertFalse(plan['coverage']['inventory_complete'])
        self.assertEqual(plan['status'], 'partial')
        self.assertEqual(plan['coverage']['prepared_targets'], 1)

    def test_diagnostic_change_gets_new_key_without_immutable_collision(self):
        """Input: pathless index row removed between prepares. Output: distinct immutable plan keys."""
        row = self.source('raw/platform/learn/day/operators.md', '### rank\nRank.\n')
        self.write('machine/source_index.jsonl', json.dumps(row) + '\n' + json.dumps(dict(contents='unknown')))
        first = prepare_full_semantic_compile(self.root, {})
        original = (self.root / first['plan_path']).read_bytes()
        self.write('machine/source_index.jsonl', json.dumps(row))
        second = prepare_full_semantic_compile(self.root, {})
        self.assertNotEqual(first['content_key'], second['content_key'])
        self.assertEqual((self.root / first['plan_path']).read_bytes(), original)
        self.assertEqual(first['identity']['diagnostics'], first['diagnostics'])
        self.assertEqual(second['status'], 'prepared')
        self.assertEqual(second['content_key'], prepare_full_semantic_compile(self.root, {})['content_key'])

    def test_report_headings_are_evidence_not_operator_targets(self):
        """Input: indexed research report with identifier headings. Output: evidence dependency, zero bogus operators."""
        path = 'raw/research/report.md'
        source = self.source(path, '### Conclusion\nMeasured result.\n### rank\nA report heading.\n')
        plan = prepare_full_semantic_compile(self.root, {})
        self.assertEqual(self.inventory(plan), [])
        self.assertEqual(plan['jobs'], [])
        evidence = plan['identity']['sources'][path]
        self.assertTrue(evidence['source_validated'])
        self.assertEqual(evidence['actual_sha256'], source['content_hash'])

    def test_explicit_operator_targets_select_only_contract_headings(self):
        """Input: report explicitly scoped to rank. Output: only rank target, entire report evidence retained."""
        path = 'raw/research/report.md'
        row = self.source(path, '### Conclusion\nResult.\n### rank\nRank definition.\n')
        row['target_ids'] = ['rank']
        self.write('machine/source_index.jsonl', json.dumps(row))
        plan = prepare_full_semantic_compile(self.root, {})
        self.assertEqual([t['identity'] for t in self.inventory(plan)], [dict(operator='rank')])
        self.assertEqual(plan['coverage']['prepared_targets'], 1)

    def test_operator_like_report_filename_does_not_invent_json_operator(self):
        """Input: generic named JSON in research path containing operator substring. Output: no inferred operator."""
        self.source('raw/research/operator_review.json', json.dumps(dict(name='Conclusion', definition='Report')))
        self.assertEqual(self.inventory(prepare_full_semantic_compile(self.root, {})), [])

    def extracts(self, count=3, description_bytes=0, padding_bytes=None):
        """Input: extract count/description size ints. Output: original path and independently certified subset paths."""
        from wqb.knowledge_contracts import extract_field_source_subset
        from wqb.semantic_compilation import MAX_SOURCE_BYTES
        original = 'raw/platform/data_fields/2026-10-23/data_fields.jsonl'
        rows = [dict(self.field('f' + str(i), description='x' * description_bytes or 'Closing price'),
                     capture_generation_id='fixture', generated_at='2026-10-23T00:00:00Z',
                     endpoint='/data-fields') for i in range(count)]
        padding_bytes = MAX_SOURCE_BYTES if padding_bytes is None else padding_bytes
        self.write(original, ''.join(json.dumps(row) + '\n' for row in rows) + '\n' * padding_bytes)
        self.write('raw/platform/data_fields/2026-10-23/manifest.json', dict(
            generated_at=rows[0]['generated_at'], capture_generation_id='fixture', scope=rows[0]['scope'],
            certification_status='complete', field_count=count, error_count=0))
        paths = [extract_field_source_subset(self.root, original,
            [dict(dataset_id='prices', field_id=row['field']['id'], scope=row['scope'])])['excerpt_path']
            for row in rows]
        return original, paths

    def test_multiple_extracts_use_constant_original_and_index_scans(self):
        """Input: three certified extracts sharing a large capture. Output: at most two original/three index reads."""
        original, paths = self.extracts()
        reads = dict(original=0, index=0)
        open_path = Path.open

        def counted(path, *args, **kwargs):
            """Input: Path/open arguments. Output: real stream, counting only fixture original/index reads."""
            if path == self.root / original:
                reads['original'] += 1
            if path == self.root / 'machine/source_index.jsonl':
                reads['index'] += 1
            return open_path(path, *args, **kwargs)

        with patch.object(Path, 'open', counted):
            plan = prepare_full_semantic_compile(self.root, {})
        self.assertEqual(plan['coverage']['prepared_targets'], len(paths))
        self.assertLessEqual(reads['original'], 2, reads)
        self.assertLessEqual(reads['index'], 3, reads)

    def test_batch_proofs_preserve_individual_material_and_default_verifier(self):
        """Input: three extracts. Output: session material matches ordinary independent verification."""
        from wqb.knowledge_contracts import verify_field_source_extracts, verify_field_source_extract
        from wqb.semantic_compilation import _material
        _, paths = self.extracts()
        rows = {row['path']: row for row in map(json.loads,
            (self.root / 'machine/source_index.jsonl').read_text(encoding='utf-8').splitlines())}
        session = verify_field_source_extracts(self.root, paths)
        for path in paths:
            self.assertEqual(_material(self.root, rows[path], _verification_session=session),
                             _material(self.root, rows[path]))
            self.assertEqual(session.proof(path), verify_field_source_extract(self.root, path))
        session.finalize()

    def test_small_original_also_uses_only_scan_and_final_digest_read(self):
        """Input: three extracts sharing a bounded original. Output: two original reads, complete inventory."""
        original, paths = self.extracts(padding_bytes=0)
        reads = []
        open_path = Path.open

        def counted(path, *args, **kwargs):
            """Input: Path/open arguments. Output: real stream; track shared original reads only."""
            if path == self.root / original:
                reads.append(path)
            return open_path(path, *args, **kwargs)

        with patch.object(Path, 'open', counted):
            plan = prepare_full_semantic_compile(self.root, {})
        self.assertEqual(plan['coverage']['prepared_targets'], len(paths))
        self.assertEqual(len(reads), 2)

    def test_shared_scan_does_not_raise_individual_extract_byte_bound(self):
        """Input: aggregate selected bytes above 512KB, each extract below it. Output: valid independent proofs."""
        from wqb.knowledge_contracts import verify_field_source_extracts
        _, paths = self.extracts(description_bytes=180_000)
        self.assertGreater(sum((self.root / path).stat().st_size for path in paths), 512_000)
        session = verify_field_source_extracts(self.root, paths)
        for path in paths:
            self.assertEqual(session.proof(path)['status'], 'verified')
        session.finalize()

    def test_shared_scan_does_not_apply_thirty_row_limit_to_union(self):
        """Input: 31 one-row extracts. Output: 31 verified proofs without weakening each extract's row bound."""
        from wqb.knowledge_contracts import verify_field_source_extracts
        original, paths = self.extracts(count=31)
        reads = dict(original=0, index=0)
        open_path = Path.open

        def counted(path, *args, **kwargs):
            """Input: Path/open arguments. Output: real stream and constant scan counters."""
            if path == self.root / original:
                reads['original'] += 1
            if path == self.root / 'machine/source_index.jsonl':
                reads['index'] += 1
            return open_path(path, *args, **kwargs)

        with patch.object(Path, 'open', counted):
            session = verify_field_source_extracts(self.root, paths)
            self.assertTrue(all(session.proof(path)['selected_rows'] == 1 for path in paths))
            session.finalize()
        self.assertEqual(reads, dict(original=2, index=2))

    def test_session_rejects_source_and_receipt_tampering(self):
        """Input: altered original and separately altered receipt. Output: no reused successful proofs."""
        from wqb.knowledge_contracts import verify_field_source_extracts
        original, paths = self.extracts()
        raw = (self.root / original).read_bytes()
        (self.root / original).write_bytes(raw + b'\n')
        session = verify_field_source_extracts(self.root, paths)
        for path in paths:
            with self.assertRaises(ValueError):
                session.proof(path)
        (self.root / original).write_bytes(raw)
        key = Path(paths[0]).stem.removeprefix('semantic-subset-')
        receipt = self.root / 'machine/semantic_jobs' / key / 'field_source_extract.json'
        value = json.loads(receipt.read_bytes())
        value['row_receipts'][0]['row_sha256'] = '0' * 64
        receipt.write_text(json.dumps(value), encoding='utf-8')
        session = verify_field_source_extracts(self.root, paths)
        with self.assertRaises(ValueError):
            session.proof(paths[0])
        self.assertEqual(session.proof(paths[1])['status'], 'verified')

    def test_final_mutations_invalidate_session_even_with_restored_stats(self):
        """Input: post-verification original/manifest/index/receipt/excerpt byte mutations. Output: invalid session."""
        from wqb.knowledge_contracts import verify_field_source_extracts
        original, paths = self.extracts()
        key = Path(paths[0]).stem.removeprefix('semantic-subset-')
        evidence = [original, 'raw/platform/data_fields/2026-10-23/manifest.json',
                    'machine/source_index.jsonl', 'machine/semantic_jobs/' + key + '/field_source_extract.json', paths[0]]
        for relative in evidence:
            with self.subTest(evidence=relative):
                session = verify_field_source_extracts(self.root, paths)
                path = self.root / relative
                raw, stat = path.read_bytes(), path.stat()
                path.write_bytes(raw[:-1] + (b' ' if raw[-1:] != b' ' else b'\n'))
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                with self.assertRaisesRegex(ValueError, 'changed|mutat'):
                    session.finalize()
                with self.assertRaises(ValueError):
                    session.proof(paths[1])
                with self.assertRaises(ValueError):
                    session.original(original)
                path.write_bytes(raw)

    def test_prepare_final_check_prevents_publication_after_original_mutation(self):
        """Input: original changes after last extract consumption with restored stat. Output: no prepared plan write."""
        import wqb.full_semantic_compile as module
        original, paths = self.extracts()
        material = module._material

        def mutate(root, row, **kwargs):
            """Input: normal material arguments. Output: material, with a deliberate late fixture mutation."""
            result = material(root, row, **kwargs)
            if row['path'] == sorted(paths)[-1]:
                path = self.root / original
                raw, stat = path.read_bytes(), path.stat()
                path.write_bytes(raw[:-1] + b' ')
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            return result

        with patch.object(module, '_material', mutate), self.assertRaisesRegex(ValueError, 'changed|mutat'):
            prepare_full_semantic_compile(self.root, {})
        self.assertEqual(list((self.root / 'machine/semantic_jobs').glob('*/plan.json')), [])

    def test_material_rejects_persisted_claimed_verification(self):
        """Input: caller-supplied verified dict. Output: rejection, not a provenance bypass."""
        from wqb.semantic_compilation import _material
        _, paths = self.extracts()
        rows = {row['path']: row for row in map(json.loads,
            (self.root / 'machine/source_index.jsonl').read_text(encoding='utf-8').splitlines())}
        with self.assertRaises(ValueError):
            _material(self.root, rows[paths[0]], _verification_session={'status': 'verified'})

    def test_material_rejects_session_from_another_root(self):
        """Input: genuine session bound to a different vault. Output: no cross-root proof reuse."""
        from wqb.knowledge_contracts import verify_field_source_extracts
        from wqb.semantic_compilation import _material
        _, paths = self.extracts(padding_bytes=0)
        rows = {row['path']: row for row in map(json.loads,
            (self.root / 'machine/source_index.jsonl').read_text(encoding='utf-8').splitlines())}
        session = verify_field_source_extracts(self.root, paths)
        with self.assertRaisesRegex(ValueError, 'session'):
            _material(self.root / 'different-vault', rows[paths[0]], _verification_session=session)
        session.finalize()

    def test_optional_bulk_preparation_supplies_missing_bounded_material(self):
        """Input: oversized capture without excerpts. Output: bounded jobs, two original reads, no ledger changes."""
        from wqb.semantic_compilation import MAX_SOURCE_BYTES
        original = 'raw/platform/data_fields/2026-10-23/data_fields.jsonl'
        rows = [dict(self.field('f%03d' % i), capture_generation_id='fixture',
                     generated_at='2026-10-23T00:00:00Z', endpoint='/data-fields') for i in range(65)]
        self.write(original, ''.join(json.dumps(row) + '\n' for row in rows) + '\n' * MAX_SOURCE_BYTES)
        self.write('raw/platform/data_fields/2026-10-23/manifest.json', dict(
            generated_at=rows[0]['generated_at'], capture_generation_id='fixture', scope=rows[0]['scope'],
            certification_status='partial', field_count=65, error_count=1))
        ledger = self.write('machine/data_ledger.jsonl', json.dumps(dict(dataset_id='prices', field_id='f000')))
        before = ledger.read_bytes()
        reads, open_path = [], Path.open

        def counted(path, *args, **kwargs):
            """Input: Path/open arguments. Output: real stream, counting only original reads."""
            if path == self.root / original and (not args or 'r' in args[0]):
                reads.append(path)
            return open_path(path, *args, **kwargs)

        config = dict(local_field_extracts=dict(source_paths=[original], max_batches=3, max_fields=65))
        with patch.object(Path, 'open', counted):
            plan = prepare_full_semantic_compile(self.root, config)
        self.assertEqual(plan['coverage']['prepared_targets'], 65)
        self.assertEqual(plan['model_calls'], 0)
        self.assertEqual(plan['budget']['model_call_budget'], 0)
        self.assertEqual(len(reads), 2)
        self.assertEqual(ledger.read_bytes(), before)
        self.assertTrue(all(t['freshness_status'] == 'not_evaluated' for t in self.inventory(plan)))
        second = prepare_full_semantic_compile(self.root, config)
        self.assertEqual(plan['content_key'], second['content_key'])
        self.assertEqual(plan['local_field_extracts']['selected_fields'], 65)

    def test_bulk_config_invalid_options_rejected_before_preparation(self):
        """Input: invalid opt-in bounds/types. Output: ValueError without frozen jobs."""
        for option in [True, {}, dict(source_paths=[], max_batches=0), dict(source_paths=[], max_fields=True)]:
            with self.assertRaises(ValueError):
                prepare_full_semantic_compile(self.root, dict(local_field_extracts=option))
        self.assertFalse((self.root / 'machine/semantic_jobs').exists())

    def test_optional_preparation_preserves_other_existing_capture_sessions(self):
        """Input: empty new-source selection plus existing excerpts. Output: ordinary two-read verification retained."""
        original, _ = self.extracts()
        reads, open_path = [], Path.open

        def counted(path, *args, **kwargs):
            """Input: Path/open arguments. Output: real file with original read count."""
            if path == self.root / original:
                reads.append(path)
            return open_path(path, *args, **kwargs)

        with patch.object(Path, 'open', counted):
            plan = prepare_full_semantic_compile(self.root, dict(local_field_extracts=dict(source_paths=[])))
        self.assertEqual(plan['coverage']['prepared_targets'], 3)
        self.assertEqual(len(reads), 2)


if __name__ == '__main__':
    unittest.main()
