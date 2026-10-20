import json
from pathlib import Path
import tempfile
import unittest

import requests

from wqb import knowledge_recovery as recovery
from wqb.run_readiness import ReadinessReport
from wqb.run_readiness import evaluate_run_readiness


NOW = "2026-10-11T12:00:00+00:00"
CONFIG = {"region": "USA", "delay": 1, "universe": "TOP3000", "batch_size": 30}


class FakeClient:
    def __init__(self, failures=None):
        self.failures = failures or {}
        self.calls = []
        self.timeout_seconds = 999
        self.max_retries = 4

    def get_json(self, path):
        self.calls.append(path)
        if path in self.failures:
            response = requests.Response()
            response.status_code = self.failures[path]
            raise requests.HTTPError(response=response)
        if path == "/operators":
            return [{"name": "rank", "category": "Cross Sectional", "description": "Ranks"}]
        if path.startswith("/tutorial-pages/"):
            return {"id": path.rsplit("/", 1)[-1], "content": "Official requirements"}
        if path.startswith(("/events", "/competitions")):
            return {"results": [{"id": "current"}], "count": 1}
        if path.startswith("/data-sets?"):
            return getattr(self, "dataset_payload", {"results": [{"id": "dataset-current"}], "count": 100})
        return {"id": "account"}

    def options_json(self, path):
        self.calls.append(path)
        if path in self.failures:
            response = requests.Response()
            response.status_code = self.failures[path]
            raise requests.HTTPError(response=response)
        if path == "/simulations":
            return {"actions": {"POST": {"settings": {"children": {
                "instrumentType": {"choices": ["EQUITY"]},
                "region": {"choices": {"EQUITY": ["USA"]}},
                "universe": {"choices": {"EQUITY": {"USA": ["TOP3000"]}}},
                "delay": {"choices": {"EQUITY": {"USA": [0, 1]}}},
            }}}}}
        return {"actions": {"GET": {"board": {"choices": []}}}}


class ActualShapeClient(FakeClient):
    def options_json(self, path):
        payload = super().options_json(path)
        if path == "/simulations":
            fields = payload["actions"]["POST"]["settings"]["children"]
            fields["region"]["choices"] = {"instrumentType": {"EQUITY": [{"value": "USA"}]}}
            fields["universe"]["choices"] = {"instrumentType": {"EQUITY": {"region": {"USA": [{"value": "TOP3000"}]}}}}
            fields["delay"]["choices"] = {"instrumentType": {"EQUITY": {"region": {"USA": [{"value": 0}, {"value": 1}]}}}}
            if getattr(self, "unsupported_universe", False):
                fields["universe"]["choices"]["instrumentType"]["EQUITY"]["region"]["USA"] = [{"value": "TOP500"}]
        return payload


class KnowledgeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "knowledge"
        self.machine = self.root / "machine"
        self.machine.mkdir(parents=True)
        self.run = self.base / "run"
        self.manifest = [
            {"name": name, "path": path, "updated_at": "2026-08-11", "max_age_days": 90}
            for name, path in [
                ("data_ledger", "machine/data_ledger.jsonl"),
                ("template_library", "machine/template_library.jsonl"),
                ("benchmark_rules", "machine/benchmark_rules.jsonl"),
                ("activity_snapshot", "raw/platform/activities/bootstrap_activity_snapshot.md"),
                ("operator_catalog", "machine/operator_ledger.jsonl"),
                ("scope_matrix", "machine/scope_matrix.jsonl"),
            ]
        ]
        self.write(self.machine / "freshness_manifest.json", self.manifest)
        self.scope = {"region": "EUR", "delay": 1, "universe": "TOP2500", "instrument_type": "EQUITY"}
        (self.machine / "scope_matrix.jsonl").write_text(json.dumps(self.scope) + "\n")
        (self.machine / "data_ledger.jsonl").write_text(json.dumps({"source_updated_at": "2026-07-30"}) + "\n")
        self.before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.compile_calls = 0
        self.compile_error = False
        self.gate_kwargs = {}
        self.gate_result = ReadinessReport("research", NOW, True, False, [])
        self.real_gate = False
        original_compile = recovery.run_knowledge_maintenance
        original_gate = recovery.evaluate_run_readiness
        recovery.run_knowledge_maintenance = self.compile_fixture
        recovery.evaluate_run_readiness = self.gate_fixture
        self.addCleanup(setattr, recovery, "run_knowledge_maintenance", original_compile)
        self.addCleanup(setattr, recovery, "evaluate_run_readiness", original_gate)

    def write(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def compile_fixture(self, root, **kwargs):
        self.compile_calls += 1
        if self.compile_error:
            raise RuntimeError("compile failed")
        # Model the known compiler timestamp laundering and scope truncation.
        rows = json.loads((root / "machine/freshness_manifest.json").read_text())
        for row in rows:
            row["updated_at"] = NOW[:10]
            row["max_age_days"] = 7
        self.write(root / "machine/freshness_manifest.json", rows)
        (root / "machine/scope_matrix.jsonl").write_text("")
        return {"status": "completed"}

    def gate_fixture(self, root, **kwargs):
        self.gate_kwargs = kwargs
        return evaluate_run_readiness(root, **kwargs) if self.real_gate else self.gate_result

    def recover(self, client=None, config=None):
        return recovery.recover_knowledge(self.root, config or CONFIG, NOW, self.run, client or FakeClient())

    def test_optional_404_completes_with_warning_and_mandatory_rule(self):
        client = FakeClient({"/tutorial-pages/multiplier-rules": 404})
        result = self.recover(client)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["warnings"][0]["path"], "/tutorial-pages/multiplier-rules")
        self.assertIn("/tutorial-pages/consultant-submission-tests", client.calls)
        staged = Path(result["knowledge_root"])
        pages = list((staged / "raw/platform/learn").rglob("documentation_pages.md"))
        self.assertIn("consultant-submission-tests", pages[0].read_text())
        self.assertTrue(Path(result["receipt_path"]).is_file())

    def test_mandatory_404_blocks_even_when_readiness_mock_passes(self):
        result = self.recover(FakeClient({"/tutorial-pages/consultant-submission-tests": 404}))
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["errors"])

    def test_optional_non404_is_blocking(self):
        self.assertEqual(self.recover(FakeClient({"/tutorial-pages/multiplier-rules": 503}))["status"], "blocked")

    def test_global_vault_unchanged_and_platform_ages_preserved(self):
        result = self.recover()
        self.assertEqual(self.before, {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        staged = Path(result["knowledge_root"])
        manifest = {row["name"]: row for row in json.loads((staged / "machine/freshness_manifest.json").read_text())}
        self.assertEqual(manifest["data_ledger"]["updated_at"], "2026-07-30")
        self.assertEqual(manifest["data_ledger"]["max_age_days"], 90)
        self.assertEqual(manifest["operator_catalog"]["updated_at"], NOW[:10])
        self.assertEqual(manifest["activity_snapshot"]["updated_at"], NOW[:10])
        self.assertIn(self.scope, recovery._read_rows(staged / "machine/scope_matrix.jsonl"))

    def test_failed_operator_fetch_never_gains_freshness(self):
        result = self.recover(FakeClient({"/operators": 503}))
        rows = json.loads((Path(result["knowledge_root"]) / "machine/freshness_manifest.json").read_text())
        self.assertEqual(next(r for r in rows if r["name"] == "operator_catalog")["updated_at"], "2026-08-11")
        self.assertEqual(result["status"], "blocked")

    def test_original_scope_and_live_gate_are_not_relaxed(self):
        result = self.recover()
        self.assertEqual(result["status"], "completed")
        kwargs = self.gate_kwargs
        self.assertTrue(kwargs["live_api_enabled"])
        self.assertEqual((kwargs["region"], kwargs["delay"], kwargs["universe"]), ("USA", 1, "TOP3000"))
        self.assertEqual(kwargs["mode"], "research")

    def test_actual_gate_block_cannot_be_overridden_by_compile_success(self):
        self.gate_result = ReadinessReport("research", NOW, False, True, [])
        self.assertEqual(self.recover()["status"], "blocked")

    def test_same_day_retry_reuses_receipt_without_fetch_or_compile(self):
        client = FakeClient()
        first = self.recover(client)
        calls = list(client.calls)
        second = self.recover(client)
        self.assertEqual(first["receipt_path"], second["receipt_path"])
        self.assertEqual(client.calls, calls)
        self.assertEqual(self.compile_calls, 1)

    def test_blocked_attempt_is_deduplicated_too(self):
        client = FakeClient({"/operators": 503})
        self.recover(client)
        calls = list(client.calls)
        self.assertEqual(self.recover(client)["status"], "blocked")
        self.assertEqual(client.calls, calls)

    def test_injected_client_has_bounded_transport(self):
        client = FakeClient()
        self.recover(client)
        self.assertEqual(client.max_retries, 0)
        self.assertLessEqual(client.timeout_seconds, 30)

    def test_compile_exception_is_durable_block(self):
        self.compile_error = True
        result = self.recover()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(Path(result["receipt_path"]).is_file())

    def test_real_evaluator_rejects_incomplete_fixture(self):
        self.real_gate = True
        self.assertEqual(self.recover()["status"], "blocked")

    def test_completed_receipt_rechecks_readiness_without_refetch(self):
        client = FakeClient()
        self.assertEqual(self.recover(client)["status"], "completed")
        calls = list(client.calls)
        self.gate_result = ReadinessReport("research", NOW, False, True, [])
        self.assertEqual(self.recover(client)["status"], "blocked")
        self.assertEqual(client.calls, calls)

    def test_partial_activity_capture_blocks_and_keeps_original_age(self):
        client = FakeClient()
        original_get = client.get_json

        def partial(path):
            payload = original_get(path)
            return {"count": 100, "results": [{"id": "partial"}]} if path.startswith("/events") else payload

        client.get_json = partial
        result = self.recover(client)
        self.assertEqual(result["status"], "blocked")
        rows = json.loads((Path(result["knowledge_root"]) / "machine/freshness_manifest.json").read_text())
        self.assertEqual(next(r for r in rows if r["name"] == "activity_snapshot")["updated_at"], "2026-08-11")

    def test_immutable_evidence_does_not_change_on_retry(self):
        client = FakeClient()
        first = self.recover(client)
        sources = {path: Path(path).read_bytes() for path in first["evidence"]["sources"]}
        self.recover(client)
        self.assertTrue(sources)
        self.assertEqual(sources, {path: Path(path).read_bytes() for path in sources})

    def test_interrupted_claim_never_repeats_network(self):
        result = self.recover()
        receipt = Path(result["receipt_path"])
        self.write(receipt, {"phase": "captured"})
        client = FakeClient()
        self.assertEqual(self.recover(client)["status"], "blocked")
        self.assertEqual(client.calls, [])

    def test_real_compile_cannot_launder_source_freshness(self):
        from wqb.knowledge_maintenance import run_knowledge_maintenance

        recovery.run_knowledge_maintenance = run_knowledge_maintenance
        result = self.recover()
        rows = json.loads((Path(result["knowledge_root"]) / "machine/freshness_manifest.json").read_text())
        self.assertEqual(next(r for r in rows if r["name"] == "data_ledger")["updated_at"], "2026-07-30")

    def test_scope_matrix_live_validation_refreshes_scoped_age_without_losing_global_breadth(self):
        for row in self.manifest:
            if row["name"] == "scope_matrix":
                row["max_age_days"] = 30
        self.write(self.machine / "freshness_manifest.json", self.manifest)
        result = self.recover()
        staged = Path(result["knowledge_root"])
        rows = json.loads((staged / "machine/freshness_manifest.json").read_text())
        self.assertEqual(next(r for r in rows if r["name"] == "scope_matrix")["updated_at"], NOW[:10])
        self.assertIn(self.scope, recovery._read_rows(staged / "machine/scope_matrix.jsonl"))
        self.assertEqual(next(r for r in rows if r["name"] == "scope_matrix")["validated_scope"],
                         {"region": "USA", "delay": 1, "universe": "TOP3000"})

    def test_settings_failure_does_not_refresh_scope_matrix(self):
        result = self.recover(FakeClient({"/simulations": 503}))
        self.assertEqual(result["status"], "blocked")
        rows = json.loads((Path(result["knowledge_root"]) / "machine/freshness_manifest.json").read_text())
        self.assertEqual(next(r for r in rows if r["name"] == "scope_matrix")["updated_at"], "2026-08-11")

    def test_empty_dataset_probe_blocks_without_claiming_field_recapture(self):
        client = FakeClient()
        original_get = client.get_json

        def empty(path):
            return {"results": [], "count": 0} if path.startswith("/data-sets?") else original_get(path)

        client.get_json = empty
        result = self.recover(client)
        self.assertEqual(result["status"], "blocked")

    def test_effective_root_alias_and_frozen_run_scope(self):
        self.write(self.run / "runtime/original_batch_scope.json", {"settings": CONFIG})
        result = self.recover(config={"region": "EUR", "delay": 0, "universe": "TOP500", "batch_size": 30})
        self.assertEqual(result["scope"], {"region": "USA", "delay": 1, "universe": "TOP3000"})
        self.assertEqual(result["effective_root"], result["knowledge_root"])

    def test_compiler_cannot_retimestamp_other_scope_rows(self):
        self.scope["generated_at"] = "2026-08-11T00:00:00+00:00"
        (self.machine / "scope_matrix.jsonl").write_text(json.dumps(self.scope) + "\n")
        original_compile = self.compile_fixture

        def retimestamp(root, **kwargs):
            result = original_compile(root, **kwargs)
            row = {**self.scope, "generated_at": NOW}
            (root / "machine/scope_matrix.jsonl").write_text(json.dumps(row) + "\n")
            return result

        recovery.run_knowledge_maintenance = retimestamp
        result = self.recover()
        self.assertIn(self.scope, recovery._read_rows(Path(result["knowledge_root"]) / "machine/scope_matrix.jsonl"))

    def test_actual_dependency_name_wrappers_validate_original_scope(self):
        result = self.recover(ActualShapeClient())
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["evidence"]["scope_validation"]["passed"])

    def test_unsupported_wrapped_choice_identifies_field(self):
        client = ActualShapeClient()
        client.unsupported_universe = True
        result = self.recover(client)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any(row.get("field") == "universe" for row in result["errors"]))

    def test_dataset_requires_id_and_rejects_supplied_scope_mismatch(self):
        for row in ({}, {"id": ""}, {"id": "ds", "region": "EUR"},
                    {"id": "ds", "scope": {"delay": 0}}, {"id": "ds", "instrumentType": "FUTURES"}):
            with self.subTest(row=row):
                self.run = self.base / ("run-" + str(len(list(self.base.glob("run-*")))))
                client = FakeClient()
                client.dataset_payload = {"results": [row], "count": 100, "next": "/data-sets?offset=1"}
                result = self.recover(client)
                self.assertEqual(result["status"], "blocked")

    def test_dataset_probe_accepts_valid_id_scope_and_remaining_pages(self):
        client = FakeClient()
        client.dataset_payload = {"results": [{"id": "ds", "scope": {"region": "USA", "delay": 1, "universe": "TOP3000"}}],
                                  "count": 100, "next": "/data-sets?offset=1"}
        result = self.recover(client)
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["evidence"]["scope_validation"]["field_recapture"])

    def test_changed_source_revision_allows_one_new_attempt_preserving_history(self):
        original_revision = recovery._source_code_revision
        self.addCleanup(setattr, recovery, "_source_code_revision", original_revision)
        recovery._source_code_revision = lambda: "old-code"
        first = self.recover(FakeClient({"/operators": 503}))
        old_path = Path(first["receipt_path"])
        old_bytes = old_path.read_bytes()
        recovery._source_code_revision = lambda: "fixed-code"
        client = FakeClient()
        second = self.recover(client)
        self.assertEqual(second["status"], "completed")
        self.assertNotEqual(first["receipt_path"], second["receipt_path"])
        self.assertEqual(old_bytes, old_path.read_bytes())
        self.assertEqual(second["source_code_revision"], "fixed-code")
        calls = list(client.calls)
        self.recover(client)
        self.assertEqual(calls, client.calls)


if __name__ == "__main__":
    unittest.main()
