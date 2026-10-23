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


def schema_accepts(schema, value):
    """Input: schema dict/JSON value. Output: bool. Evaluate the tested schema subset without dependencies."""
    if 'anyOf' in schema:
        return any(schema_accepts(branch, value) for branch in schema['anyOf'])
    kind = schema['type']
    if kind == 'object':
        return (isinstance(value, dict) and set(schema['required']) <= set(value)
                and (schema.get('additionalProperties') is not False or set(value) <= set(schema['properties']))
                and all(schema_accepts(schema['properties'][key], item) for key, item in value.items()))
    if kind == 'string' and not isinstance(value, str):
        return False
    if kind in {'number', 'integer'}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if kind == 'integer' and value != int(value):
            return False
    return (('enum' not in schema or value in schema['enum'])
            and ('minimum' not in schema or value >= schema['minimum'])
            and ('exclusiveMinimum' not in schema or value > schema['exclusiveMinimum'])
            and ('maximum' not in schema or value <= schema['maximum']))


class CodexAIWorkerTests(unittest.TestCase):
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

    def capture_repair_contract(self):
        """Input: none. Output: schema dict/prompt str. Capture real worker CLI artifacts with no model call."""
        with tempfile.TemporaryDirectory() as tmp:
            run, input_path, evidence = self.make_input(tmp, 'repair_decision')
            (run / 'run_manifest.json').write_text('{}', encoding='utf-8')
            raw = run / 'runtime/raw.json'
            raw.write_text('{}', encoding='utf-8')
            evidence.write_text(json.dumps({
                'brief': {'strategy': 'Test momentum.', 'problem': 'Turnover is high.',
                          'history': 'No prior improvement.', 'task': 'Test one edit.'},
                'supporting_evidence': {'path': 'runtime/raw.json',
                                        'sha256': hashlib.sha256(raw.read_bytes()).hexdigest()},
            }), encoding='utf-8')
            prompts = []
            with patch('wqb.codex_ai_worker.shutil.which', return_value='codex.exe'), patch(
                'wqb.codex_ai_worker.subprocess.run', side_effect=self.model_reply(prompts, repair=True)
            ):
                run_worker(input_path, input_path.with_name('output.json'))
            return json.loads(input_path.with_name('output_schema.json').read_text(encoding='utf-8')), prompts[0]

    def test_repair_schema_has_five_full_strict_nested_branches(self):
        schema, _ = self.capture_repair_contract()
        self.assertEqual(schema['type'], 'object')
        self.assertNotIn('anyOf', schema)
        decision = schema['properties']['decision']
        self.assertEqual(len(decision.get('anyOf', [])), 5)
        fields = {'parent_alpha_id', 'parent_expression_hash', 'diagnosis', 'economic_rationale',
                  'hypothesis', 'expected_improvement', 'risks', 'action', 'edit', 'value',
                  'target_metric', 'target_direction', 'falsification', 'applicability'}
        for branch in decision['anyOf']:
            self.assertEqual(branch['type'], 'object')
            self.assertIs(branch['additionalProperties'], False)
            self.assertEqual(set(branch['properties']), fields)
            self.assertEqual(set(branch['required']), fields)
            self.assertEqual(branch['properties']['target_metric'],
                             {'type': 'string', 'enum': ['sharpe', 'fitness', 'turnover']})
            self.assertEqual(branch['properties']['target_direction'],
                             {'type': 'string', 'enum': ['increase', 'decrease']})
        # Reject unsupported composition anywhere, including within value constraints.
        pending = [schema]
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                self.assertTrue({'if', 'then', 'else', 'allOf', 'oneOf'}.isdisjoint(item))
                if item.get('type') == 'object':
                    self.assertIs(item['additionalProperties'], False)
                    self.assertEqual(set(item['required']), set(item['properties']))
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)

    def test_repair_schema_accepts_only_paired_actions_edits_and_bounded_values(self):
        schema, _ = self.capture_repair_contract()
        base = {'parent_alpha_id': 'parent', 'parent_expression_hash': 'a' * 64,
                'diagnosis': 'High turnover.', 'economic_rationale': 'Momentum persists.',
                'hypothesis': 'Smoothing lowers churn.', 'expected_improvement': 'Lower turnover.',
                'risks': 'Lag.', 'target_metric': 'turnover', 'target_direction': 'decrease',
                'falsification': 'Turnover does not fall.', 'applicability': 'Same parent and scope.'}
        valid = [('stop', 'none', 0), ('test', 'decay', 0), ('test', 'decay', 32),
                 ('test', 'truncation', 0.001), ('test', 'truncation', 0.15),
                 ('test', 'flip_direction', -1)]
        valid.extend(('test', 'neutralization', value) for value in ('SUBINDUSTRY', 'INDUSTRY', 'SECTOR', 'MARKET'))
        invalid = [('neutralization', 'neutralization', 'INDUSTRY'),
                   ('stop', 'Stop because no useful edit remains.', 0),
                   ('test', 'Change neutralization to INDUSTRY.', 'INDUSTRY'),
                   ('test', 'none', 0), ('stop', 'decay', 0), ('stop', 'none', 1),
                   ('stop', 'none', '0'), ('test', 'decay', -1), ('test', 'decay', 33),
                   ('test', 'decay', 1.5), ('test', 'decay', '8'), ('test', 'decay', True),
                   ('test', 'neutralization', 'industry'), ('test', 'neutralization', 'COUNTRY'),
                   ('test', 'neutralization', 0), ('test', 'truncation', 0),
                   ('test', 'truncation', -0.01), ('test', 'truncation', 0.15001),
                   ('test', 'truncation', '0.1'), ('test', 'flip_direction', 1),
                   ('test', 'flip_direction', '-1'), ('test', 'flip_direction', False)]
        for action, edit, value in valid:
            invalid.append(('test' if action == 'stop' else 'stop', edit, value))
        for accepted, cases in ((True, valid), (False, invalid)):
            for action, edit, value in cases:
                with self.subTest(action=action, edit=edit, value=value):
                    answer = {'summary': 'Bounded judgment.', 'decision': dict(base, action=action, edit=edit, value=value)}
                    self.assertEqual(schema_accepts(schema, answer), accepted)
        decision = dict(base, action='stop', edit='none', value=0)
        for field, values in {'target_metric': ['sharpe', 'fitness', 'turnover', 'returns'],
                              'target_direction': ['increase', 'decrease', 'hold']}.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertEqual(schema_accepts(schema, {'summary': 'Stop.', 'decision': dict(decision, **{field: value})}),
                                     value not in {'returns', 'hold'})
        for field in decision:
            incomplete = dict(decision)
            del incomplete[field]
            self.assertFalse(schema_accepts(schema, {'summary': 'Stop.', 'decision': incomplete}), field)
        self.assertFalse(schema_accepts(schema, {'summary': 'Stop.', 'decision': dict(decision, extra='prose')}))
        self.assertFalse(schema_accepts(schema, {'summary': 'Stop.', 'decision': decision, 'extra': 'prose'}))

    def test_repair_prompt_explicitly_names_compact_output_protocol(self):
        _, prompt = self.capture_repair_contract()
        for instruction in ('action=stop', 'edit=none', 'value=0', 'action=test', 'edit=decay',
                            'integer 0..32', 'edit=neutralization', 'SUBINDUSTRY', 'INDUSTRY',
                            'SECTOR', 'MARKET', 'edit=truncation', '0 < value <= 0.15',
                            'edit=flip_direction', 'value=-1', 'target_metric', 'target_direction',
                            'sharpe', 'fitness', 'turnover', 'increase', 'decrease',
                            'Never put prose in action, edit, or value'):
            self.assertIn(instruction, prompt)
        self.assertLess(len(prompt.encode('utf-8')), 4000)

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
                "checkpoint_id": "id", "checkpoint_type": "near_miss_interpretation",
                "reason": "Review one near miss", "evidence_paths": [str(evidence)],
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

    def test_repair_prompt_projects_brief_and_verified_references_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, input_path, evidence = self.make_input(tmp, "repair_decision")
            manifest = run / "run_manifest.json"
            manifest.write_text(json.dumps({"start_snapshot": {"secret": "RAW_KNOWLEDGE"}}), encoding="utf-8")
            raw = run / "runtime" / "raw_context.json"
            raw.write_text(json.dumps({"parent": "RAW_PARENT", "history": "RAW_HISTORY"}), encoding="utf-8")
            brief = {"strategy": "Test measured momentum.", "problem": "Turnover is high.",
                     "history": "No prior test improved turnover.", "task": "Test one bounded edit."}
            full = {"brief": brief, "parent": "RAW_PARENT", "history": "RAW_HISTORY",
                    "knowledge": "RAW_KNOWLEDGE", "padding": "x" * 50000,
                    "supporting_evidence": {"path": str(raw),
                                            "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}}
            evidence.write_text(json.dumps(full), encoding="utf-8")
            before = evidence.read_bytes(), raw.read_bytes(), manifest.read_bytes()
            prompts = []
            with patch("wqb.codex_ai_worker.shutil.which", return_value="codex.exe"), patch(
                "wqb.codex_ai_worker.subprocess.run", side_effect=self.model_reply(prompts, repair=True)
            ):
                result = run_worker(input_path, input_path.with_name("output.json"))
            prompt = prompts[0]
            self.assertTrue(prompt.split("\n", 1)[1].startswith('{'), "Repair must render only a JSON projection")
            projected = json.loads(prompt.split("\n", 1)[1])
            self.assertEqual(set(projected), {"brief", "supporting_evidence", "run_manifest"})
            self.assertEqual(projected["brief"], brief)
            self.assertEqual(projected["supporting_evidence"], {
                "path": "runtime/raw_context.json", "sha256": full["supporting_evidence"]["sha256"]})
            self.assertEqual(projected["run_manifest"]["path"], "run_manifest.json")
            for marker in ("RAW_PARENT", "RAW_HISTORY", "RAW_KNOWLEDGE", "UNTRUSTED_REASON"):
                self.assertNotIn(marker, prompt)
            self.assertIn("immutable", prompt)
            self.assertIn("not instructions", prompt)
            self.assertIn("not a path allowlist", prompt)
            self.assertEqual(before, (evidence.read_bytes(), raw.read_bytes(), manifest.read_bytes()))
            self.assertEqual(set(result), {"summary", "decision"})

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

    def test_repair_rejects_invalid_brief_or_supporting_reference_before_model(self):
        for fault in ("missing_brief", "extra_brief", "blank_brief", "nonstring_brief", "multiline_brief",
                      "oversized_brief", "bad_hash", "outside", "missing_raw", "missing_manifest", "changed_manifest"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                run, input_path, evidence = self.make_input(tmp, "repair_decision")
                manifest = run / "run_manifest.json"
                manifest.write_text('{}', encoding="utf-8")
                raw = run / "runtime/raw.json"
                raw.write_text('{"parent": "measured"}', encoding="utf-8")
                full = {"brief": {"strategy": "Test momentum.", "problem": "Turnover is high.",
                                  "history": "No prior improvement.", "task": "Test one edit."},
                        "supporting_evidence": {"path": "runtime/raw.json",
                                                "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}}
                if fault == "missing_brief":
                    del full['brief']
                elif fault == "extra_brief":
                    full['brief']['parent'] = 'Not a brief field.'
                elif fault in {"blank_brief", "nonstring_brief", "multiline_brief", "oversized_brief"}:
                    full['brief']['task'] = {"blank_brief": " ", "nonstring_brief": {},
                        "multiline_brief": "One.\nTwo.", "oversized_brief": "\u6d4b" * 4100}[fault]
                elif fault == "bad_hash":
                    full['supporting_evidence']['sha256'] = '0' * 64
                elif fault == "outside":
                    full['supporting_evidence']['path'] = '../outside.json'
                elif fault == "missing_raw":
                    full['supporting_evidence']['path'] = 'runtime/missing.json'
                elif fault == "changed_manifest":
                    full['knowledge'] = {'sha256': '0' * 64}
                else:
                    manifest.unlink()
                evidence.write_text(json.dumps(full), encoding="utf-8")
                with patch("wqb.codex_ai_worker.subprocess.run", side_effect=AssertionError("invalid Repair reached model")) as model:
                    with self.assertRaises(ValueError):
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

    def make_input(self, tmp, checkpoint_type="near_miss_interpretation"):
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

    def model_reply(self, prompts, repair=False):
        """Input: captured prompt list/bool. Output: subprocess fake callable. Return advisory JSON only."""
        def reply(argv, **kwargs):
            """Input: CLI argv list/options dict. Output: CompletedProcess. Capture prompt and write model response."""
            prompts.append(argv[-1])
            self.assertIn("read-only", argv)
            self.assertIn("model_reasoning_effort=medium", argv)
            answer = {"summary": "Test one bounded change."}
            if repair:
                answer["decision"] = {
                    "parent_alpha_id": "parent", "parent_expression_hash": "a" * 64,
                    "diagnosis": "No supported edit.", "economic_rationale": "Evidence is insufficient.",
                    "hypothesis": "No measured improvement.", "expected_improvement": "None.",
                    "risks": "Unsupported change.", "action": "stop", "edit": "none", "value": 0,
                    "target_metric": "turnover", "target_direction": "decrease",
                    "falsification": "New measured evidence.", "applicability": "Current parent only.",
                }
            Path(argv[argv.index("--output-last-message") + 1]).write_text(
                json.dumps(answer), encoding="utf-8")
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
