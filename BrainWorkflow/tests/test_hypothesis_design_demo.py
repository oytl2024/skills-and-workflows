"""Developer offline demo tests; no real model or platform calls."""

import json
import hashlib
from copy import deepcopy
import io
from contextlib import redirect_stdout
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_hypothesis_design import compiler_fixture
from tests.test_hypothesis_design_acceptance import audit_fixture


class HypothesisDemoTests(unittest.TestCase):
    def source_backed_input(self, *, integer=True):
        """Input: fixture integer-premise bool. Output: raw design/resources; actual-format facts, explicitly fake capture/window."""
        from tests.test_hypothesis_design import source_backed_compiler_fixture
        from tests.test_resource_evidence import named_comparison_fixture, operator_fixture
        from wqb.knowledge_contracts import parse_markdown_front_matter, render_front_matter
        design, resources, _ = source_backed_compiler_fixture()
        timing, field, scope, index, texts = named_comparison_fixture()
        operator, op_index, op_texts = operator_fixture('ts_delta', integer=integer)
        renames = {path: path.replace('/learn/', '/learn/operator-') for path in op_index}
        for old, new in renames.items():
            row = deepcopy(op_index[old])
            metadata, body = parse_markdown_front_matter(op_texts[old])
            row['path'] = new
            metadata['path'] = new
            text = render_front_matter(metadata) + body
            row['file_sha256'] = hashlib.sha256(text.encode()).hexdigest()
            index[new], texts[new] = row, text
        def relocate(value):
            """Input: JSON fixture object. Output: None. Relocate evidence paths without altering located facts."""
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'source_path' and item in renames:
                        value[key] = renames[item]
                    else:
                        relocate(item)
            elif isinstance(value, list):
                for item in value:
                    relocate(item)
        relocate(operator)
        field_path = 'raw/platform/data_fields/fields.jsonl'
        from wqb.knowledge_contracts import extract_field_source_subset
        from wqb.semantic_compilation import _material
        from scripts.capture_learn_material import capture_resource_subset
        from tests.test_capture_learn_material import FakeLearnClient
        self.fixture_vault = self.root / ('source-vault-' + str(integer))
        payload = dict(name='ts_delta', category='Time Series', scope=['COMBO', 'REGULAR'], level='ALL',
            documentation='/operators/ts_delta', definition='ts_delta(x, d)',
            description=operator['definition']['description'])
        transport = FakeLearnClient({'/operators/ts_delta': payload})
        capture_result = capture_resource_subset(self.fixture_vault, transport,
            [dict(kind='operator_detail', id='ts_delta')], scope['as_of'])
        self.assertEqual(transport.paths, ['/operators/ts_delta'])
        self.assertEqual(capture_result['errors'], [])
        operator_path = Path(capture_result['raw_markdown_files'][0]).relative_to(self.fixture_vault).as_posix()
        captured_index = [json.loads(line) for line in (self.fixture_vault / 'machine/source_index.jsonl').read_text().splitlines()]
        operator_index, operator_text = _material(self.fixture_vault, next(row for row in captured_index if row['path'] == operator_path))
        signature = operator['definition_basis']['signature_premise']
        previous = signature['evidence_ref']['source_path']
        del index[previous], texts[previous]
        index[operator_path], texts[operator_path] = operator_index, operator_text
        for ref in [signature['evidence_ref'], *operator['definition']['evidence_refs']]:
            if ref['source_path'] == previous:
                ref.update(source_path=operator_path, sha256=operator_index['content_hash'])
        _, operator_body = parse_markdown_front_matter(operator_text.replace('\r\n', '\n'))
        signature['locator']['quote'] = operator_body.split('### `ts_delta`', 1)[1].split('\n## Raw GET Receipt', 1)[0].strip()
        operator['definition_basis']['definition_digest'] = hashlib.sha256(json.dumps(
            operator['definition'], sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        original_path = 'raw/platform/data_fields/2026-10-15/data_fields.jsonl'
        original = self.fixture_vault / original_path
        original.parent.mkdir(parents=True)
        captured = json.loads(texts.pop(field_path))
        captured['capture_generation_id'] = 'offline-fixture'
        original.write_text(json.dumps(captured) + '\n', encoding='utf-8')
        (original.parent / 'manifest.json').write_text(json.dumps(dict(scope=captured['scope'],
            generated_at=captured['generated_at'], capture_generation_id='offline-fixture',
            certification_status='complete', field_count=1, error_count=0)), encoding='utf-8')
        del index[field_path]
        extracted = extract_field_source_subset(self.fixture_vault, original_path,
            [dict(dataset_id=field['dataset_id'], field_id=field['field_id'], scope=captured['scope'])])
        field_path = extracted['excerpt_path']
        entries = [json.loads(line) for line in (self.fixture_vault / 'machine/source_index.jsonl').read_text().splitlines()]
        field_index, field_text = _material(self.fixture_vault, next(row for row in entries if row['path'] == field_path))
        index[field_path], texts[field_path] = field_index, field_text
        capture_premise = timing['premises'][-1]
        capture_premise['evidence_ref'].update(source_path=field_path, sha256=field_index['content_hash'])
        capture_premise['locator']['expected_value'] = captured
        field.update(timing_contract=timing, field_description='A captured measurement.',
                     semantic_tags=[], source_paths=[field_path])
        pack = resources['evidence_pack']
        pack.update(scope=scope, source_index=index, source_texts=texts)
        resources.update(field_rows=[field], operator_rows=[operator], source_index=index, source_texts=texts)
        raw = {key: value for key, value in design.items() if key != 'design_id'}
        raw['trigger_id'] = field_path
        raw['evidence_refs'][0].update(source_path=field_path, sha256=index[field_path]['content_hash'])
        raw['experiment_plan']['treatments'] = [dict(feature=dict(kind='change',
            input=dict(kind='role', role='pulse'), horizon=5), rationale='Fixture-only comparison of change and level.')]
        path = self.root / ('source-backed-' + str(integer) + '.json')
        path.write_text(json.dumps(dict(resources=resources, answer=dict(
            summary='OFFLINE fixture; captured row and integer constraint are fictional.', designs=[raw]))), encoding='utf-8')
        return path, resources

    def test_v2_pair_demo_and_immutable_release_keep_source_contracts(self):
        """Input: actual-format offline proposal. Output: two unreviewed immutable drafts with policy/type receipts."""
        from wqb.semantic_publication import stage_semantic_release, publish_semantic_release, read_semantic_release
        source, resources = self.source_backed_input()
        out = self.root / 'paired-output'
        result = self.run_demo(source, out)
        self.assertEqual(result['status'], 'compiled', (out / 'diagnostics.json').read_text())
        drafts = json.loads((out / 'drafts.json').read_text())
        experiment = json.loads((out / 'experiment.json').read_text())[0]
        self.assertEqual(len(drafts), 2)
        self.assertEqual(experiment['resource_contract_version'], 2)
        self.assertFalse(experiment['context_bindings']['pulse']['timing_receipt']['historical_pit_verified'])
        self.assertEqual(len({arm['binding']['bound_expression'] for arm in experiment['arms']}), 2)
        self.assertTrue(all(row['semantic_status'] == 'unreviewed' and row['status'] == 'scout_only' for row in drafts))
        vault = self.fixture_vault
        (vault / 'wiki').mkdir(parents=True)
        refs = []
        for path, text in resources['source_texts'].items():
            target = vault / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode())
            refs.append(dict(path=path, sha256=hashlib.sha256(text.encode()).hexdigest()))
        proposals = dict(resource_contract_version=2, validated_operators=resources['operator_rows'],
                         validated_templates=drafts, source_refs=refs, wiki_materials={})
        staged = stage_semantic_release(vault, proposals, '2026-10-15T00:00:00Z')
        receipt = publish_semantic_release(vault, staged)
        self.assertEqual(read_semantic_release(vault), receipt)
        self.assertEqual(publish_semantic_release(vault, staged), receipt)
        self.assertEqual(self.run_demo(source, out), result)

    def test_missing_real_window_fact_cannot_produce_a_pair(self):
        """Input: same fixture without fictional integer fact. Output: no complete pair or false readiness."""
        source, _ = self.source_backed_input(integer=False)
        out = self.root / 'unsupported-output'
        result = self.run_demo(source, out)
        self.assertEqual(result['status'], 'rejected')
        self.assertFalse(result['research_authorized'])
        self.assertEqual(json.loads((out / 'experiment.json').read_text()), [])

    def setUp(self):
        """Input: TestCase. Output: None. Keep demo inputs and outputs in an isolated temporary root."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def input_file(self):
        """Input: TestCase. Output: Path. Serialize a fictional sourced design for the actual validator/compiler."""
        design, resources, scope = compiler_fixture(treatment=True)
        design.pop('design_id')
        path = self.root / 'input.json'
        path.write_text(json.dumps(dict(resources=resources,
            answer=dict(summary='A fictional offline proposal.', designs=[design]))), encoding='utf-8')
        return path

    def run_demo(self, input_path, output_path, mode='demo'):
        """Input: source/output Paths and mode str. Output: result dict. Use the real offline script API."""
        from scripts import demo_hypothesis_design
        from wqb.semantic_contracts import SemanticPolicy
        return demo_hypothesis_design.run_demo(input_path, output_path, mode, SemanticPolicy())

    def test_actual_compilation_and_byte_stable_replay(self):
        source = self.input_file()
        before = source.read_bytes()
        out = self.root / 'output'
        result = self.run_demo(source, out)
        self.assertEqual(result['status'], 'compiled')
        self.assertEqual(result['draft_count'], 2)
        files = {path.name: path.read_bytes() for path in out.iterdir()}
        self.assertEqual(set(files), {'design.json', 'drafts.json', 'experiment.json', 'coverage.json', 'diagnostics.json'})
        self.assertTrue(all(row['semantic_status'] == 'unreviewed' for row in json.loads(files['drafts.json'])))
        self.assertEqual(self.run_demo(source, out), result)
        self.assertEqual(files, {path.name: path.read_bytes() for path in out.iterdir()})
        self.assertEqual(source.read_bytes(), before)

    def test_rejected_design_outputs_no_fake_templates(self):
        source = self.input_file()
        payload = json.loads(source.read_text(encoding='utf-8'))
        payload['answer']['designs'][0]['prediction_direction'] = 'unknown'
        source.write_text(json.dumps(payload), encoding='utf-8')
        out = self.root / 'output'
        result = self.run_demo(source, out)
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(json.loads((out / 'drafts.json').read_text(encoding='utf-8')), [])
        self.assertTrue(json.loads((out / 'diagnostics.json').read_text(encoding='utf-8')))

    def test_refuses_input_directory_or_canonical_authority_destination(self):
        source = self.input_file()
        for out in [self.root, self.root / 'machine' / 'semantic_jobs', self.root / '.git']:
            with self.subTest(out=out), self.assertRaises(ValueError):
                self.run_demo(source, out)
        self.assertFalse((self.root / 'machine').exists())

    def test_conflicting_existing_output_is_not_overwritten(self):
        source = self.input_file()
        out = self.root / 'output'
        out.mkdir()
        path = out / 'drafts.json'
        path.write_text('preserve this file', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            self.run_demo(source, out)
        self.assertEqual(path.read_text(encoding='utf-8'), 'preserve this file')
        self.assertEqual([path.name for path in out.iterdir()], ['drafts.json'])

    def test_audit_mode_reports_source_gaps_without_vault_mutation(self):
        vault = self.root / 'knowledge'
        scope, template = audit_fixture(vault)
        source = self.root / 'audit-input.json'
        source.write_text(json.dumps(dict(knowledge_root=str(vault), scope=scope,
            template_requirements=[template])), encoding='utf-8')
        before = {path.relative_to(vault).as_posix(): path.read_bytes() for path in vault.rglob('*') if path.is_file()}
        result = self.run_demo(source, self.root / 'output', 'audit')
        self.assertEqual(result['status'], 'usable_subset')
        self.assertFalse(result['research_authorized'])
        with self.assertRaises(ValueError):
            self.run_demo(source, vault / 'exports', 'audit')
        self.assertEqual(before, {path.relative_to(vault).as_posix(): path.read_bytes() for path in vault.rglob('*') if path.is_file()})

    def test_late_output_collision_cannot_claim_success(self):
        source = self.input_file()
        out = self.root / 'output'
        original = Path.mkdir

        def collide(path, *args, **kwargs):
            """Input: Path and mkdir arguments. Output: None. Simulate another writer after output preflight."""
            result = original(path, *args, **kwargs)
            if path == out:
                (out / 'design.json').write_text('unexpected late file', encoding='utf-8')
            return result

        with patch.object(Path, 'mkdir', collide), self.assertRaises(FileExistsError):
            self.run_demo(source, out)
        self.assertEqual((out / 'design.json').read_text(encoding='utf-8'), 'unexpected late file')

    def test_product_local_run_directory_is_protected(self):
        from scripts import demo_hypothesis_design as demo
        source = self.input_file()
        local_run = Path(demo.__file__).resolve().parents[1] / 'runs' / 'do-not-write-demo'
        with self.assertRaises(ValueError):
            demo._output_directory(source, local_run, {})

    def test_crlf_existing_bytes_do_not_pass_byte_stable_replay(self):
        source = self.input_file()
        out = self.root / 'output'
        self.run_demo(source, out)
        path = out / 'drafts.json'
        content = path.read_bytes().replace(b'\n', b'\r\n')
        path.write_bytes(content)
        with self.assertRaises(FileExistsError):
            self.run_demo(source, out)
        self.assertEqual(path.read_bytes(), content)

    def test_directory_link_replacement_after_compile_is_refused(self):
        from scripts import demo_hypothesis_design as demo
        source = self.input_file()
        out = self.root / 'output'
        original = demo.compile_hypothesis_design
        original_link = Path.is_symlink
        replaced = False

        def compile_then_replace(*args):
            """Input: real compiler arguments. Output: real result; simulate a directory becoming linked afterward."""
            nonlocal replaced
            result = original(*args)
            replaced = True
            return result

        def linked(path):
            """Input: Path. Output: bool. Simulate a late link without Windows symlink privileges."""
            return replaced and path == out or original_link(path)

        with patch.object(demo, 'compile_hypothesis_design', compile_then_replace), patch.object(Path, 'is_symlink', linked):
            with self.assertRaises(ValueError):
                self.run_demo(source, out)
        self.assertFalse(out.exists())

    def test_cli_reports_success_and_rejection_without_platform(self):
        from scripts import demo_hypothesis_design as demo
        source = self.input_file()
        out = self.root / 'output'
        args = ['demo_hypothesis_design', '--mode', 'demo', '--evidence-pack', str(source), '--output-dir', str(out)]
        stdout = io.StringIO()
        with patch('sys.argv', args), redirect_stdout(stdout):
            self.assertEqual(demo.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue())['status'], 'compiled')
        source.write_text('{invalid json', encoding='utf-8')
        stdout = io.StringIO()
        with patch('sys.argv', args), redirect_stdout(stdout):
            self.assertEqual(demo.main(), 2)
        self.assertEqual(json.loads(stdout.getvalue())['error_type'], 'JSONDecodeError')

    def test_unknown_envelope_keys_leave_no_output_directory(self):
        source = self.input_file()
        payload = json.loads(source.read_text(encoding='utf-8'))
        payload['publish'] = True
        source.write_text(json.dumps(payload), encoding='utf-8')
        out = self.root / 'output'
        with self.assertRaises(ValueError):
            self.run_demo(source, out)
        self.assertFalse(out.exists())

    def test_persisted_job_root_is_protected(self):
        source = self.input_file()
        job = self.root / 'external-job'
        job.mkdir()
        (job / 'run_manifest.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.run_demo(source, job / 'exports')
        self.assertFalse((job / 'exports').exists())

    def test_direct_script_entry_replays_identical_artifacts(self):
        from scripts import demo_hypothesis_design as demo
        source = self.input_file()
        out = self.root / 'output'
        command = [sys.executable, str(Path(demo.__file__).resolve()), '--mode', 'demo',
                   '--evidence-pack', str(source), '--output-dir', str(out)]
        first = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)['draft_count'], 2)
        before = {path.name: path.read_bytes() for path in out.iterdir()}
        second = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(before, {path.name: path.read_bytes() for path in out.iterdir()})


if __name__ == '__main__':
    unittest.main()
