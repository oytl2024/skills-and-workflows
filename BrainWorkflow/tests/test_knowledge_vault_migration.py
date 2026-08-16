import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wqb.knowledge_freshness import evaluate_knowledge_contract_health
from wqb.knowledge_maintenance import run_knowledge_maintenance
from wqb.knowledge_vault_migration import run_knowledge_vault_migration


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """Input: path and rows. Output: none. Write deterministic JSONL fixtures."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_mixed_legacy_vault(root: Path) -> None:
    """Input: vault root. Output: none. Create the old mixed structure that blocked real cleanup."""
    capture = root / "raw" / "platform" / "data_fields" / "2026-07-30"
    scope = {"instrument_type": "EQUITY", "region": "EUR", "delay": 0, "universe": "TOP500"}
    write_jsonl(
        capture / "data_fields.jsonl",
        [
            {
                "generated_at": "2026-07-30T00:00:00+00:00",
                "scope": scope,
                "data_set": {"id": "fundamental6", "name": "Fundamental 6", "category": "fundamental"},
                "field": {"id": "fnd6_cash_quality", "type": "MATRIX", "coverage": 0.7, "alphaCount": 1, "userCount": 1},
            }
        ],
    )
    write_jsonl(
        capture / "scopes.jsonl",
        [
            {
                "generated_at": "2026-07-30T00:00:00+00:00",
                "scope": scope,
                "status": "completed",
                "certification_status": "complete",
            }
        ],
    )
    write_jsonl(
        capture / "data_sets.jsonl",
        [{"generated_at": "2026-07-30T00:00:00+00:00", "scope": scope, "data_set": {"id": "fundamental6"}}],
    )
    (capture / "errors.jsonl").write_text("", encoding="utf-8")
    (capture / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-07-30T00:00:00+00:00",
                "scope_count": 1,
                "data_set_count": 1,
                "field_count": 1,
                "error_count": 0,
                "status": "completed",
                "certification_status": "complete",
                "requested_matrix": [scope],
            }
        ),
        encoding="utf-8",
    )
    (capture / "index.md").write_text("# Platform Data Field Capture\n", encoding="utf-8")
    (capture / "operators.json").write_text(
        json.dumps({"generated_at": "2026-07-30T00:00:00+00:00", "operators": [{"name": "group_rank", "category": "group"}]}),
        encoding="utf-8",
    )

    write_jsonl(
        root / "wiki" / "20_semantics" / "data_ledger.jsonl",
        [
            {
                "dataset_id": "legacy_dataset",
                "field_id": "legacy_field",
                "field_type": "MATRIX",
                "region": "USA",
                "delay": 1,
                "universe": "TOP3000",
                "semantic_tags": ["cash"],
                "coverage": 0.5,
                "alpha_count": 0,
                "user_count": 0,
                "simulation_usage_count": 0,
                "submitted_usage_count": 0,
                "last_used_at": "",
                "best_result_label": "legacy",
                "correlation_risk": "low",
                "source_paths": ["wiki/20_semantics/data_ledger.jsonl"],
                "source_quality": "legacy_compiled",
                "coverage_status": "partial",
                "source_updated_at": "2026-07-29",
                "available_scopes": [{"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}],
            }
        ],
    )
    write_jsonl(
        root / "wiki" / "30_templates" / "template_library.jsonl",
        [
            {
                "template_id": "cash_quality_reversion",
                "hypothesis": "Cash quality changes can mean revert after overreaction.",
                "skeleton": "rank(ts_delta({field}, 20))",
                "required_field_types": ["MATRIX"],
                "compatible_semantic_tags": ["cash"],
                "operator_tags": ["time_series_change"],
                "status": "seed",
                "correlation_risk": "low",
                "repair_levers": ["neutralize_sector"],
                "source_paths": [
                    "knowledge/wiki/20_semantics/operators.md",
                    "wiki/30_templates/template_families.md",
                ],
            }
        ],
    )
    write_jsonl(root / "wiki" / "50_benchmarks" / "benchmark_rules.jsonl", [])
    (root / "wiki" / "80_maintenance" / "freshness_manifest.json").parent.mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "80_maintenance" / "freshness_manifest.json").write_text("[]", encoding="utf-8")
    (root / "wiki" / "10_foundations" / "activity_snapshot.md").parent.mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "10_foundations" / "activity_snapshot.md").write_text("# Activity\nPower Pool is active.\n", encoding="utf-8")
    (root / "wiki" / "20_semantics" / "operators.md").write_text("# Operators\n", encoding="utf-8")
    (root / "wiki" / "30_templates" / "template_families.md").write_text("# Template Families\n", encoding="utf-8")
    (root / "wiki" / "40_experiments").mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "40_experiments" / "2026-07-03-existing-scan-submit-candidate.md").write_text(
        "# Existing Scan Submit Candidate\n",
        encoding="utf-8",
    )
    (root / "wiki" / "40_experiments" / "research_record_compile.json").write_text(
        json.dumps(
            {
                "report_type": "research_record_compile",
                "generated_at": "2026-07-30T00:00:00+00:00",
                "record_count": 1,
                "source_paths": ["wiki/40_experiments/2026-07-03-existing-scan-submit-candidate.md"],
                "case_report_paths": ["wiki/60_research_cases/2026-07-03-existing-scan-submit-candidate.md"],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (root / "wiki" / "00_principles" / "old.md").parent.mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "00_principles" / "old.md").write_text("# Old principles\n", encoding="utf-8")
    (root / "wiki" / "90_index" / "glossary.md").parent.mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "90_index" / "glossary.md").write_text("# Glossary\n", encoding="utf-8")


class KnowledgeVaultMigrationTests(unittest.TestCase):
    def test_migration_preserves_legacy_activity_snapshot_after_wiki_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")

            snapshot = root / "raw" / "platform" / "activities" / "bootstrap_activity_snapshot.md"
            self.assertIn("Power Pool is active", snapshot.read_text(encoding="utf-8"))

    def test_migration_does_not_overwrite_existing_activity_snapshot_with_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            snapshot = root / "raw" / "platform" / "activities" / "bootstrap_activity_snapshot.md"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text("# Activity Snapshot\n\nReal current activity evidence.\n", encoding="utf-8")

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")

            self.assertIn("Real current activity evidence", snapshot.read_text(encoding="utf-8"))
            self.assertNotIn("No platform activity snapshot", snapshot.read_text(encoding="utf-8"))

    def test_migration_materializes_machine_resources_and_source_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)

            report = run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")

            machine = root / "machine"
            for name in (
                "scope_matrix.jsonl",
                "data_ledger.jsonl",
                "operator_ledger.jsonl",
                "template_library.jsonl",
                "benchmark_rules.jsonl",
                "research_records.jsonl",
                "source_index.jsonl",
            ):
                self.assertTrue((machine / name).exists(), name)
                self.assertTrue((machine / name).read_text(encoding="utf-8").strip(), name)
            self.assertTrue((machine / "freshness_manifest.json").exists())
            self.assertIn("group_rank", (machine / "operator_ledger.jsonl").read_text(encoding="utf-8"))
            self.assertIn("raw/platform/data_fields/2026-07-30/index.md", (root / "raw" / "source_index.md").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "completed")

    def test_migration_moves_root_raw_references_into_canonical_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)
            root_raw = root / "raw" / "karpathy_llm_knowledge_bases_20260702.md"
            stage1 = root / "raw" / "research" / "stage1" / "2026-07-stage1-source-inventory.md"
            root_raw.write_text("# LLM Knowledge Bases\n", encoding="utf-8")
            stage1.parent.mkdir(parents=True, exist_ok=True)
            stage1.write_text("# Stage 1 Source Inventory\n", encoding="utf-8")

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")

            moved_reference = root / "raw" / "community" / "user_messages" / "2026-07-02" / "karpathy_llm_knowledge_bases.md"
            moved_stage1 = root / "raw" / "research" / "runs" / "2026-07-stage1-source-inventory.md"
            self.assertFalse(root_raw.exists())
            self.assertFalse(stage1.exists())
            self.assertTrue(moved_reference.exists())
            self.assertTrue(moved_stage1.exists())
            self.assertIn("source_type", moved_reference.read_text(encoding="utf-8"))
            self.assertIn("source_type", moved_stage1.read_text(encoding="utf-8"))

    def test_migration_preserves_root_readme_and_legacy_wiki_markdown_as_raw_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)
            root_readme = root / "README.md"
            legacy_wiki = root / "wiki" / "60_workflows" / "stage1_operating_contract.md"
            root_readme.write_text("# Old Vault Readme\n", encoding="utf-8")
            legacy_wiki.parent.mkdir(parents=True, exist_ok=True)
            legacy_wiki.write_text("# Old Workflow Contract\n", encoding="utf-8")

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            report = run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)

            source_index = (root / "raw" / "source_index.md").read_text(encoding="utf-8")
            self.assertEqual(report["status"], "completed")
            self.assertFalse(root_readme.exists())
            self.assertFalse(legacy_wiki.exists())
            self.assertIn("raw/community/user_messages/2026-07-30/legacy_knowledge_root_README.md", source_index)
            self.assertIn("raw/community/user_messages/2026-07-30/legacy_wiki/60_workflows__stage1_operating_contract.md", source_index)

    def test_migration_allows_cleanup_to_remove_old_active_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)
            (root / ".obsidian").mkdir(parents=True)

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            report = run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)
            health = evaluate_knowledge_contract_health(root)

            self.assertEqual(report["status"], "completed")
            self.assertEqual(health["issue_count"], 0)
            self.assertFalse((root / "wiki" / "20_semantics").exists())
            self.assertFalse((root / "wiki" / "30_templates").exists())
            self.assertFalse((root / "wiki" / "50_benchmarks").exists())
            self.assertFalse((root / "wiki" / "00_principles").exists())
            self.assertFalse((root / "wiki" / "90_index").exists())
            self.assertTrue((root / ".obsidian").exists())

    def test_migration_normalizes_machine_resource_legacy_source_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)

            templates = [
                json.loads(line)
                for line in (root / "machine" / "template_library.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            machine_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (root / "machine").glob("*.json*")
            )
            self.assertIn(
                "raw/community/user_messages/2026-07-30/legacy_wiki/30_templates__template_families.md",
                templates[0]["source_paths"],
            )
            self.assertIn(
                "raw/community/user_messages/2026-07-30/legacy_wiki/20_semantics__operators.md",
                templates[0]["source_paths"],
            )
            self.assertNotIn("wiki/20_semantics/", machine_text)
            self.assertNotIn("wiki/30_templates/", machine_text)
            self.assertNotIn("wiki/40_experiments/", machine_text)
            self.assertNotIn("wiki/50_benchmarks/", machine_text)
            self.assertNotIn("wiki/60_workflows/", machine_text)

    def test_migration_preserves_legacy_research_compile_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)

            rows = [
                json.loads(line)
                for line in (root / "machine" / "research_records.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            legacy = next(row for row in rows if row["run_id"] == "legacy_research_record_compile")
            source_paths = legacy["triage"][0]["source_paths"]
            self.assertFalse((root / "wiki" / "40_experiments" / "research_record_compile.json").exists())
            self.assertTrue((root / "raw" / "research" / "runs" / "legacy_wiki_experiments" / "research_record_compile.md").exists())
            self.assertEqual("compiled_from_legacy_research_compile_report", legacy["final_state"])
            self.assertIn(
                "raw/research/runs/legacy_wiki_experiments/40_experiments__2026-07-03-existing-scan-submit-candidate.md",
                source_paths,
            )
            self.assertEqual(
                "raw/research/runs/legacy_wiki_experiments/research_record_compile.md",
                legacy["legacy_compile_report_path"],
            )

    def test_migration_normalizes_existing_research_record_legacy_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            old_case = root / "wiki" / "40_experiments" / "old_case.md"
            old_case.parent.mkdir(parents=True, exist_ok=True)
            old_case.write_text("# Old Case\n", encoding="utf-8")
            write_jsonl(
                root / "machine" / "research_records.jsonl",
                [
                    {
                        "run_id": "existing",
                        "triage": [
                            {
                                "benchmark_label": "legacy",
                                "failed": [],
                                "source_paths": ["wiki/40_experiments/old_case.md"],
                            }
                        ],
                    }
                ],
            )

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)

            rows = [
                json.loads(line)
                for line in (root / "machine" / "research_records.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            existing = next(row for row in rows if row["run_id"] == "existing")
            self.assertEqual(
                ["raw/research/runs/legacy_wiki_experiments/40_experiments__old_case.md"],
                existing["triage"][0]["source_paths"],
            )

    def test_migration_normalizes_non_markdown_retired_references_without_archive_overmatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            legacy_json = root / "wiki" / "30_templates" / "foo.json"
            legacy_json.parent.mkdir(parents=True, exist_ok=True)
            legacy_json.write_text('{"note": "old"}', encoding="utf-8")
            write_jsonl(
                root / "wiki" / "30_templates" / "template_library.jsonl",
                [
                    {
                        "template_id": "mixed_paths",
                        "hypothesis": "Test path normalization.",
                        "skeleton": "rank({field})",
                        "required_field_types": ["MATRIX"],
                        "compatible_semantic_tags": ["cash"],
                        "operator_tags": ["rank"],
                        "status": "seed",
                        "correlation_risk": "low",
                        "repair_levers": [],
                        "source_paths": [
                            "wiki/30_templates/foo.json",
                            "docs/archive/wiki/20_semantics/operator_notes.md",
                        ],
                    }
                ],
            )

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)

            row = json.loads((root / "machine" / "template_library.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertIn(
                "raw/community/user_messages/2026-07-30/legacy_wiki/30_templates__foo_json.md",
                row["source_paths"],
            )
            self.assertIn("docs/archive/wiki/20_semantics/operator_notes.md", row["source_paths"])
            self.assertTrue(
                (root / "raw" / "community" / "user_messages" / "2026-07-30" / "legacy_wiki" / "30_templates__foo_json.md").exists()
            )

    def test_migration_preserves_curated_benchmark_rule_text_when_normalizing_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_jsonl(
                root / "wiki" / "50_benchmarks" / "benchmark_rules.jsonl",
                [
                    {
                        "rule_id": "near_miss_stable_pnl_promotion",
                        "issue_types": ["near_miss"],
                        "description": "Curated local description.",
                        "promotion_condition": "Curated local promotion condition.",
                        "action": "Curated local action.",
                        "evidence_paths": ["wiki/50_benchmarks/custom_note.md"],
                        "consumed_by": ["triage"],
                        "risk": "low",
                    }
                ],
            )
            (root / "wiki" / "50_benchmarks" / "custom_note.md").write_text("# Custom Rule Note\n", encoding="utf-8")

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")

            row = json.loads((root / "machine" / "benchmark_rules.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("Curated local description.", row["description"])
            self.assertEqual("Curated local action.", row["action"])
            self.assertEqual(
                ["raw/community/user_messages/2026-07-30/legacy_wiki/50_benchmarks__custom_note.md"],
                row["evidence_paths"],
            )

    def test_migration_repairs_existing_empty_legacy_stage1_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            legacy_raw = root / "raw" / "research" / "runs" / "legacy_wiki_experiments" / "40_experiments__old.md"
            legacy_raw.parent.mkdir(parents=True, exist_ok=True)
            legacy_raw.write_text("# Old Stage 1 Case\n", encoding="utf-8")
            write_jsonl(
                root / "machine" / "research_records.jsonl",
                [
                    {
                        "run_id": "legacy_stage1_import",
                        "objective": "Preserve migrated Stage 1 research lessons",
                        "triage": [{"benchmark_label": "legacy_stage1_lesson", "failed": [], "source_paths": []}],
                    }
                ],
            )

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")

            rows = [
                json.loads(line)
                for line in (root / "machine" / "research_records.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            stage1 = next(row for row in rows if row["run_id"] == "legacy_stage1_import")
            self.assertEqual(
                ["raw/research/runs/legacy_wiki_experiments/40_experiments__old.md"],
                stage1["triage"][0]["source_paths"],
            )

    def test_migration_normalizes_existing_stage1_raw_source_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)
            stage1 = root / "raw" / "research" / "stage1"
            stage1.mkdir(parents=True, exist_ok=True)
            (stage1 / "foo.md").write_text("# Foo Stage 1\n", encoding="utf-8")
            (stage1 / "bar.md").write_text("# Bar Stage 1\n", encoding="utf-8")
            write_jsonl(
                root / "machine" / "research_records.jsonl",
                [
                    {
                        "run_id": "existing_stage1_paths",
                        "triage": [
                            {
                                "benchmark_label": "legacy_stage1",
                                "failed": [],
                                "source_paths": [
                                    "raw/research/stage1/foo.md",
                                    "knowledge/raw/research/stage1/bar.md",
                                ],
                            }
                        ],
                    }
                ],
            )

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)

            rows = [
                json.loads(line)
                for line in (root / "machine" / "research_records.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            existing = next(row for row in rows if row["run_id"] == "existing_stage1_paths")
            self.assertFalse((root / "raw" / "research" / "stage1").exists())
            self.assertEqual(
                ["raw/research/runs/foo.md", "raw/research/runs/bar.md"],
                existing["triage"][0]["source_paths"],
            )

    def test_migration_normalizes_stage1_source_paths_to_collision_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)
            stage1 = root / "raw" / "research" / "stage1"
            runs = root / "raw" / "research" / "runs"
            stage1.mkdir(parents=True, exist_ok=True)
            runs.mkdir(parents=True, exist_ok=True)
            (runs / "foo.md").write_text("# Existing Different Foo\n", encoding="utf-8")
            (stage1 / "foo.md").write_text("# Stage 1 Foo\n", encoding="utf-8")
            write_jsonl(
                root / "machine" / "research_records.jsonl",
                [
                    {
                        "run_id": "existing_stage1_collision",
                        "triage": [
                            {
                                "benchmark_label": "legacy_stage1",
                                "failed": [],
                                "source_paths": ["raw/research/stage1/foo.md"],
                            }
                        ],
                    }
                ],
            )

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)

            rows = [
                json.loads(line)
                for line in (root / "machine" / "research_records.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            existing = next(row for row in rows if row["run_id"] == "existing_stage1_collision")
            self.assertTrue((root / "raw" / "research" / "runs" / "foo.1.md").exists())
            self.assertEqual(
                ["raw/research/runs/foo.1.md"],
                existing["triage"][0]["source_paths"],
            )

    def test_migration_preserves_nested_stage1_markdown_before_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)
            nested = root / "raw" / "research" / "stage1" / "subdir" / "note.md"
            nested.parent.mkdir(parents=True, exist_ok=True)
            nested.write_text("# Nested Stage 1 Note\n", encoding="utf-8")

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)

            migrated = root / "raw" / "research" / "runs" / "subdir__note.md"
            self.assertFalse(nested.exists())
            self.assertFalse((root / "raw" / "research" / "stage1").exists())
            self.assertTrue(migrated.exists())
            self.assertIn("Nested Stage 1 Note", migrated.read_text(encoding="utf-8"))

    def test_migration_preserves_uppercase_stage1_markdown_before_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)
            nested = root / "raw" / "research" / "stage1" / "subdir" / "note.MD"
            nested.parent.mkdir(parents=True, exist_ok=True)
            nested.write_text("# Uppercase Stage 1 Note\n", encoding="utf-8")
            original_rglob = Path.rglob

            def case_sensitive_rglob(path: Path, pattern: str):
                if path == root / "raw" / "research" / "stage1" and pattern == "*.md":
                    return (item for item in original_rglob(path, pattern) if item.suffix == ".md")
                return original_rglob(path, pattern)

            with patch.object(Path, "rglob", case_sensitive_rglob):
                run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
                run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)

            migrated = root / "raw" / "research" / "runs" / "subdir__note.md"
            self.assertFalse(nested.exists())
            self.assertFalse((root / "raw" / "research" / "stage1").exists())
            self.assertTrue(migrated.exists())
            self.assertIn("Uppercase Stage 1 Note", migrated.read_text(encoding="utf-8"))

    def test_migration_refuses_sensitive_retired_files_before_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)
            root_private = root / "private_notes.md"
            learn_private = root / "raw" / "learn" / "private" / "notes.md"
            stage1_secret = root / "raw" / "research" / "stage1" / "credentials" / "config.md"
            wiki_private = root / "wiki" / "60_workflows" / "private_contract.md"
            wiki_secret_json = root / "wiki" / "30_templates" / "secret_token.json"
            for path in (root_private, learn_private, stage1_secret, wiki_private, wiki_secret_json):
                path.parent.mkdir(parents=True, exist_ok=True)
            root_private.write_text("# Private Root Notes\n", encoding="utf-8")
            learn_private.write_text("# Private Learn Notes\n", encoding="utf-8")
            stage1_secret.write_text("# Secret Stage 1 Config\n", encoding="utf-8")
            wiki_private.write_text("# Private Wiki Contract\n", encoding="utf-8")
            wiki_secret_json.write_text('{"token": "do-not-copy"}', encoding="utf-8")

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")

            self.assertTrue(root_private.exists())
            self.assertTrue(learn_private.exists())
            self.assertTrue(stage1_secret.exists())
            self.assertTrue(wiki_private.exists())
            self.assertTrue(wiki_secret_json.exists())
            self.assertEqual("# Private Root Notes\n", root_private.read_text(encoding="utf-8"))
            self.assertEqual("# Private Learn Notes\n", learn_private.read_text(encoding="utf-8"))
            self.assertEqual("# Secret Stage 1 Config\n", stage1_secret.read_text(encoding="utf-8"))
            self.assertEqual("# Private Wiki Contract\n", wiki_private.read_text(encoding="utf-8"))
            self.assertEqual('{"token": "do-not-copy"}', wiki_secret_json.read_text(encoding="utf-8"))
            self.assertFalse((root / "raw" / "community" / "user_messages" / "2026-07-30" / "legacy_knowledge_root_private_notes.md").exists())
            self.assertFalse((root / "raw" / "platform" / "learn" / "2026-07-30" / "notes.md").exists())
            self.assertFalse((root / "raw" / "research" / "runs" / "credentials__config.md").exists())
            self.assertFalse((root / "raw" / "community" / "user_messages" / "2026-07-30" / "legacy_wiki" / "60_workflows__private_contract.md").exists())
            self.assertFalse((root / "raw" / "community" / "user_messages" / "2026-07-30" / "legacy_wiki" / "30_templates__secret_token_json.md").exists())

    def test_migration_preserves_non_markdown_retired_reference_collision_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)
            legacy_json = root / "wiki" / "30_templates" / "foo.json"
            stale_wrapper = (
                root
                / "raw"
                / "community"
                / "user_messages"
                / "2026-07-30"
                / "legacy_wiki"
                / "30_templates__foo_json.md"
            )
            legacy_json.write_text('{"note": "real old"}', encoding="utf-8")
            stale_wrapper.parent.mkdir(parents=True, exist_ok=True)
            stale_wrapper.write_text("# Stale Wrapper\n\nDifferent old evidence.\n", encoding="utf-8")
            write_jsonl(
                root / "wiki" / "30_templates" / "template_library.jsonl",
                [
                    {
                        "template_id": "collision_non_markdown_source",
                        "hypothesis": "Test collision-safe non-Markdown preservation.",
                        "skeleton": "rank({field})",
                        "required_field_types": ["MATRIX"],
                        "compatible_semantic_tags": ["cash"],
                        "operator_tags": ["rank"],
                        "status": "seed",
                        "correlation_risk": "low",
                        "repair_levers": [],
                        "source_paths": ["wiki/30_templates/foo.json"],
                    }
                ],
            )

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)

            row = json.loads((root / "machine" / "template_library.jsonl").read_text(encoding="utf-8").splitlines()[0])
            collision_wrapper = (
                root
                / "raw"
                / "community"
                / "user_messages"
                / "2026-07-30"
                / "legacy_wiki"
                / "30_templates__foo_json.1.md"
            )
            self.assertFalse(legacy_json.exists())
            self.assertTrue(collision_wrapper.exists())
            self.assertIn('"note": "real old"', collision_wrapper.read_text(encoding="utf-8"))
            self.assertEqual(
                ["raw/community/user_messages/2026-07-30/legacy_wiki/30_templates__foo_json.1.md"],
                row["source_paths"],
            )

    def test_migration_preserves_research_compile_collision_target_in_source_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)
            stale_report = root / "raw" / "research" / "runs" / "legacy_wiki_experiments" / "research_record_compile.md"
            stale_report.parent.mkdir(parents=True, exist_ok=True)
            stale_report.write_text("# Stale Research Compile\n\nDifferent old evidence.\n", encoding="utf-8")
            write_jsonl(
                root / "machine" / "research_records.jsonl",
                [
                    {
                        "run_id": "existing_compile_reference",
                        "triage": [
                            {
                                "benchmark_label": "legacy_compile_reference",
                                "failed": [],
                                "source_paths": ["wiki/40_experiments/research_record_compile.json"],
                            }
                        ],
                    }
                ],
            )

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)

            rows = [
                json.loads(line)
                for line in (root / "machine" / "research_records.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            legacy = next(row for row in rows if row["run_id"] == "legacy_research_record_compile")
            existing = next(row for row in rows if row["run_id"] == "existing_compile_reference")
            collision_report = root / "raw" / "research" / "runs" / "legacy_wiki_experiments" / "research_record_compile.1.md"
            self.assertIn("Stale Research Compile", stale_report.read_text(encoding="utf-8"))
            self.assertTrue(collision_report.exists())
            self.assertIn("Legacy Research Record Compile Report", collision_report.read_text(encoding="utf-8"))
            self.assertFalse((root / "wiki" / "40_experiments" / "research_record_compile.json").exists())
            self.assertEqual(
                "raw/research/runs/legacy_wiki_experiments/research_record_compile.1.md",
                legacy["legacy_compile_report_path"],
            )
            self.assertEqual(
                ["raw/research/runs/legacy_wiki_experiments/research_record_compile.1.md"],
                existing["triage"][0]["source_paths"],
            )

    def test_migration_preserves_retired_raw_non_markdown_before_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)
            learn_json = root / "raw" / "learn" / "operators.json"
            stage1_json = root / "raw" / "research" / "stage1" / "result.json"
            learn_json.parent.mkdir(parents=True, exist_ok=True)
            stage1_json.parent.mkdir(parents=True, exist_ok=True)
            learn_json.write_text('{"operator": "ts_rank"}', encoding="utf-8")
            stage1_json.write_text('{"alpha_id": "abc123"}', encoding="utf-8")

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            run_knowledge_maintenance(root, "2026-07-30T02:00:00+00:00", apply_cleanup=True)

            migrated_learn = root / "raw" / "platform" / "learn" / "2026-07-30" / "operators_json.md"
            migrated_stage1 = root / "raw" / "research" / "runs" / "result_json.md"
            source_index = (root / "raw" / "source_index.md").read_text(encoding="utf-8")
            self.assertFalse(learn_json.exists())
            self.assertFalse(stage1_json.exists())
            self.assertTrue(migrated_learn.exists())
            self.assertTrue(migrated_stage1.exists())
            self.assertIn('"operator": "ts_rank"', migrated_learn.read_text(encoding="utf-8"))
            self.assertIn('"alpha_id": "abc123"', migrated_stage1.read_text(encoding="utf-8"))
            self.assertIn("raw/platform/learn/2026-07-30/operators_json.md", source_index)
            self.assertIn("raw/research/runs/result_json.md", source_index)

    def test_migration_reuses_non_markdown_wrapper_after_metadata_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_mixed_legacy_vault(root)
            legacy_json = root / "wiki" / "30_templates" / "foo.json"
            legacy_json.write_text('{"note": "repeat"}', encoding="utf-8")

            run_knowledge_vault_migration(root, "2026-07-30T01:00:00+00:00")
            run_knowledge_vault_migration(root, "2026-07-30T02:00:00+00:00")

            wrappers = sorted(
                (
                    root
                    / "raw"
                    / "community"
                    / "user_messages"
                    / "2026-07-30"
                    / "legacy_wiki"
                ).glob("30_templates__foo_json*.md")
            )
            self.assertEqual(["30_templates__foo_json.md"], [path.name for path in wrappers])


if __name__ == "__main__":
    unittest.main()
