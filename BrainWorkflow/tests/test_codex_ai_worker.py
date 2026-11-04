"""Read-only Codex adapter tests; no model call in the test suite."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from wqb.codex_ai_worker import run_worker
from wqb.semantic_compilation import normalize_semantic_output


class CodexAIWorkerTests(unittest.TestCase):
    def test_retired_repair_types_rejected_before_model_or_artifact_creation(self):
        """Input: retired checkpoint types. Output: assertions. Reject locally without touching history."""
        for checkpoint_type in ('repair_decision', 'near_miss_interpretation'):
            with self.subTest(checkpoint_type=checkpoint_type), tempfile.TemporaryDirectory() as tmp:
                _, source, evidence = self.make_input(tmp, checkpoint_type)
                evidence.write_text('{}', encoding='utf-8')
                before = source.read_bytes(), evidence.read_bytes()
                with patch('wqb.codex_ai_worker.subprocess.run') as worker, patch(
                        'wqb.codex_ai_worker.subprocess.Popen') as child, patch(
                        'wqb.codex_ai_worker.shutil.which') as executable:
                    with self.assertRaisesRegex(ValueError, 'legacy AI Repair checkpoint retired'):
                        run_worker(source, source.with_name('output.json'))
                worker.assert_not_called()
                child.assert_not_called()
                executable.assert_not_called()
                self.assertEqual(before, (source.read_bytes(), evidence.read_bytes()))
                self.assertEqual(sorted(path.name for path in source.parent.iterdir()), ['input.json'])

    def test_design_worker_checks_complete_feedback_before_fake_model(self):
        from tests.test_hypothesis_design import compiler_fixture
        from tests.test_mechanism_evidence import evidence_fixture
        from wqb.mechanism_evidence import build_mechanism_evidence
        from wqb.semantic_compilation import prepare_design_job
        from wqb.semantic_contracts import SemanticPolicy
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design, resources, _ = compiler_fixture(treatment=True)
            for relative, text in resources['source_texts'].items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(text.encode())
            records, experiments = evidence_fixture()
            records[0]['backtest'][0]['error'] = 'timeout'
            feedback = build_mechanism_evidence(records, experiments)['groups']
            job = prepare_design_job(root, resources['evidence_pack'], SemanticPolicy(), resources,
                                     mechanism_feedback=feedback)
            source = job / 'stages/ai/ai_checkpoint_runs/fake/attempt/input.json'
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps(dict(checkpoint_type='hypothesis_design', evidence_paths=['materials/pack.json'])))
            def reply(argv, **kwargs):
                """Input: fake model argv/options. Output: process result; inspect only frozen feedback."""
                prompt = argv[-1]
                self.assertIn('explicit new experiment', prompt)
                self.assertIn('not causal', prompt)
                self.assertIn('operational_failure', prompt)
                self.assertIn('supporting_ref', prompt)
                self.assertNotIn('input_digest', prompt)
                self.assertIn('model_reasoning_effort=medium', argv)
                Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(dict(
                    summary='Unreviewed next proposal.', designs=[{k: v for k, v in design.items() if k != 'design_id'}])))
                return CompletedProcess(argv, 0, '', '')
            with patch('wqb.codex_ai_worker.shutil.which', return_value='fake'), patch(
                    'wqb.codex_ai_worker.subprocess.run', side_effect=reply) as model:
                run_worker(source, source.with_name('output.json'))
                self.assertEqual(model.call_count, 1)
                material = json.loads((job / 'materials/pack.json').read_text())
                ref = material['evidence_pack']['mechanism_context'][0]['supporting_ref']
                (job / ref['path']).write_text('{}')
                with self.assertRaisesRegex(ValueError, 'mechanism'):
                    run_worker(source, source.with_name('output.json'))
                self.assertEqual(model.call_count, 1)

    def test_nullable_wire_fields_do_not_hide_unknown_keys(self):
        answer = dict(summary='Unverified.', proposals=dict(operators=[], templates=[]), extra=None)
        with self.assertRaises(ValueError):
            normalize_semantic_output(answer)

    def test_semantic_worker_requires_knowledge_manifest_and_strict_proposals(self):
        for kind in ('knowledge_compile', 'research'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                run, input_path, evidence = self.make_input(tmp, 'semantic_compile')
                evidence.write_text('{}', encoding='utf-8')
                (run / 'run_manifest.json').write_text(json.dumps(dict(kind=kind, material_refs=[dict(
                    path='runtime/evidence.json', sha256=hashlib.sha256(evidence.read_bytes()).hexdigest())])), encoding='utf-8')
                def reply(argv, **kwargs):
                    """Input: fake CLI arguments. Output: process result. Inspect schema and return proposals."""
                    self.assertIn('model_reasoning_effort=medium', argv)
                    self.assertIn('read-only', argv)
                    schema = json.loads(Path(argv[argv.index('--output-schema') + 1]).read_text())
                    self.assertEqual(set(schema['properties']), {'summary', 'proposals'})
                    self.assertFalse(schema['additionalProperties'])
                    self.assertEqual(set(schema['properties']['proposals']['properties']), {'operators', 'templates'})
                    pending = [schema]
                    while pending:
                        item = pending.pop()
                        if isinstance(item, dict):
                            if item.get('type') == 'object':
                                self.assertIs(item['additionalProperties'], False)
                                self.assertEqual(set(item['required']), set(item['properties']))
                            pending.extend(item.values())
                        elif isinstance(item, list):
                            pending.extend(item)
                    Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(dict(
                        summary='Unverified.', proposals=dict(operators=[], templates=[]))), encoding='utf-8')
                    return CompletedProcess(argv, 0, '', '')
                with patch('wqb.codex_ai_worker.shutil.which', return_value='mock'), patch(
                        'wqb.codex_ai_worker.subprocess.run', side_effect=reply) as worker:
                    if kind != 'knowledge_compile':
                        with self.assertRaises(ValueError):
                            run_worker(input_path, input_path.with_name('output.json'))
                        worker.assert_not_called()
                    else:
                        result = run_worker(input_path, input_path.with_name('output.json'))
                        self.assertEqual(result['proposals'], dict(operators=[], templates=[]))

    def test_worker_limits_evidence_and_requests_medium_read_only_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            attempt = run / "stages" / "ai" / "ai_checkpoint_runs" / "id" / "attempt"
            attempt.mkdir(parents=True)
            evidence = run / "all_alphas.jsonl"
            evidence.write_text(json.dumps({"signal": "bounded evidence"}), encoding="utf-8")
            input_path = attempt / "input.json"
            output_path = attempt / "output.json"
            input_path.write_text(json.dumps({
                "checkpoint_id": "id", "checkpoint_type": "research_reflection",
                "reason": "Review bounded research evidence", "evidence_paths": [str(evidence)],
            }), encoding="utf-8")

            def fake_run(argv, **kwargs):
                self.assertIn("read-only", argv)
                self.assertIn("model_reasoning_effort=medium", argv)
                self.assertIn("--output-schema", argv)
                self.assertLess(len(argv[-1]), 40000)
                Path(argv[argv.index("--output-last-message") + 1]).write_text(
                    json.dumps({"summary": "Test one neutralization change."}), encoding="utf-8")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch("wqb.codex_ai_worker.shutil.which", return_value="codex.exe"), patch(
                "wqb.codex_ai_worker.subprocess.run", side_effect=fake_run
            ):
                result = run_worker(input_path, output_path)
            self.assertEqual(result["summary"], "Test one neutralization change.")

    def test_unicode_json_is_rendered_complete_without_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, input_path, evidence = self.make_input(tmp)
            content = {"signal": "\u6d4b\u8bd5" * 1900, "tail": "complete"}
            evidence.write_text(json.dumps(content, ensure_ascii=True), encoding="utf-8")
            prompts = []
            with patch("wqb.codex_ai_worker.shutil.which", return_value="codex.exe"), patch(
                "wqb.codex_ai_worker.subprocess.run", side_effect=self.model_reply(prompts)
            ):
                run_worker(input_path, input_path.with_name("output.json"))
            rendered = prompts[0].replace("\\", "/").split("runtime/evidence.json:\n", 1)[1]
            self.assertTrue(rendered.rstrip().endswith('}'), "JSON evidence must not be byte-sliced")
            self.assertEqual(json.loads(rendered), content)
            self.assertNotIn("\ufffd", rendered)

    def test_oversized_evidence_fails_instead_of_slicing_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, input_path, evidence = self.make_input(tmp)
            evidence.write_text(json.dumps({"signal": "x" * 12000}), encoding="utf-8")
            with patch("wqb.codex_ai_worker.subprocess.run", side_effect=AssertionError("oversized evidence reached model")) as model:
                with self.assertRaisesRegex(ValueError, "oversized"):
                    run_worker(input_path, input_path.with_name("output.json"))
            model.assert_not_called()

    def test_json_evidence_must_be_complete_object(self):
        for content in ('{"broken":', '[1, 2]'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                _, input_path, evidence = self.make_input(tmp)
                evidence.write_text(content, encoding="utf-8")
                with patch("wqb.codex_ai_worker.subprocess.run", side_effect=AssertionError("invalid JSON reached model")) as model:
                    with self.assertRaises(ValueError):
                        run_worker(input_path, input_path.with_name("output.json"))
                model.assert_not_called()

    def test_actual_rendered_prompt_is_bounded_including_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, input_path, evidence = self.make_input(tmp)
            evidence.write_text('{}', encoding="utf-8")
            checkpoint = json.loads(input_path.read_text(encoding="utf-8"))
            checkpoint["reason"] = "\u6d4b" * 12000
            input_path.write_text(json.dumps(checkpoint), encoding="utf-8")
            with patch("wqb.codex_ai_worker.subprocess.run", side_effect=AssertionError("oversized prompt reached model")) as model:
                with self.assertRaisesRegex(ValueError, "oversized"):
                    run_worker(input_path, input_path.with_name("output.json"))
            model.assert_not_called()

    def make_input(self, tmp, checkpoint_type="research_reflection"):
        """Input: temp directory str/type str. Output: three Paths. Create a bound checkpoint fixture."""
        run = Path(tmp) / "run"
        attempt = run / "stages/ai/ai_checkpoint_runs/id/attempt"
        attempt.mkdir(parents=True)
        evidence = run / "runtime/evidence.json"
        evidence.parent.mkdir()
        input_path = attempt / "input.json"
        input_path.write_text(json.dumps({"checkpoint_type": checkpoint_type,
            "reason": "UNTRUSTED_REASON", "evidence_paths": [str(evidence)]}), encoding="utf-8")
        return run, input_path, evidence

    def model_reply(self, prompts):
        """Input: prompt list. Output: fake callable. Capture read-only generic worker output."""
        def reply(argv, **kwargs):
            """Input: argv list/options dict. Output: CompletedProcess. Write fake advisory JSON."""
            prompts.append(argv[-1])
            self.assertIn("read-only", argv)
            self.assertIn("model_reasoning_effort=medium", argv)
            Path(argv[argv.index("--output-last-message") + 1]).write_text(
                json.dumps({"summary": "Test one bounded change."}), encoding="utf-8")
            return CompletedProcess(argv, 0, stdout="", stderr="")
        return reply

    def test_worker_refuses_evidence_outside_bound_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            attempt = root / "run" / "stages" / "ai" / "ai_checkpoint_runs" / "id" / "attempt"
            attempt.mkdir(parents=True)
            outside = root / "secret.txt"
            outside.write_text("private", encoding="utf-8")
            input_path = attempt / "input.json"
            input_path.write_text(json.dumps({"checkpoint_id": "id", "checkpoint_type": "x",
                                              "reason": "x", "evidence_paths": [str(outside)]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside bound run"):
                run_worker(input_path, attempt / "output.json")
