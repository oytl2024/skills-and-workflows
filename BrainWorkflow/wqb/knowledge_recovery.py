"""Bounded, run-local platform knowledge recovery; never publish to the global vault."""

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
from urllib.parse import urlencode

from scripts.capture_learn_material import (
    result_rows, write_raw_documentation_pages, write_raw_errors,
    write_raw_operators, write_raw_rows,
)
from wqb.client import WQBClient
from wqb.knowledge_contracts import parse_markdown_front_matter, render_front_matter

from wqb.knowledge_maintenance import run_knowledge_maintenance
from wqb.run_readiness import evaluate_run_readiness
from wqb.rule_refresh import refresh_incentive_snapshot


TIMEOUT_SECONDS = 15
MAX_RECOVERY_SECONDS = 180
MAX_COPY_BYTES = 2 * 1024 * 1024 * 1024
MAX_COPY_FILES = 20000
MAX_COPY_SECONDS = 60
DERIVED_RESOURCES = {"template_library", "benchmark_rules", "research_records", "source_index"}
OPTIONAL_RETIRED_PATH = "/tutorial-pages/multiplier-rules"
RECOVERY_IMPLEMENTATION_FILES = ('knowledge_recovery.py', 'knowledge_maintenance.py',
                                 'knowledge_clean_compile.py', 'knowledge_vault_migration.py')
SOURCE_CODE_REVISION = hashlib.sha256(b''.join(
    (Path(__file__).parent / name).read_bytes() for name in RECOVERY_IMPLEMENTATION_FILES)).hexdigest()


def _source_code_revision() -> str:
    """Input: None. Output: SHA256 str. Identify the loaded recovery module for bounded version-scoped attempts."""
    return SOURCE_CODE_REVISION


def _write_json(path: Path, payload: dict | list) -> None:
    """Input: Path and JSON dict/list. Output: None. Atomically persist run-local evidence."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _read_rows(path: Path) -> list[dict]:
    """Input: JSONL Path. Output: list[dict]. Read machine rows without changing source files."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _copy_vault(root: Path, destination: Path) -> None:
    """Input: source/destination Paths. Output: None. Copy only contained files, refusing linked external sources."""
    import time

    started = time.monotonic()
    total_bytes = 0
    total_files = 0

    def reject_links(directory: str, names: list[str]) -> list[str]:
        """Input: directory str and entry names list[str]. Output: empty list. Reject copy paths escaping the vault."""
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
                raise ValueError("linked source requires explicit external-file authorization")
        return []

    def bounded_copy(source: str, target: str) -> str:
        """Input: file paths str. Output: target str. Bound staging bytes, file count and elapsed copy work."""
        nonlocal total_bytes, total_files
        total_bytes += Path(source).stat().st_size
        total_files += 1
        if total_bytes > MAX_COPY_BYTES or total_files > MAX_COPY_FILES or time.monotonic() - started > MAX_COPY_SECONDS:
            raise ValueError("vault staging limit exceeded; narrow resource staging required")
        return shutil.copy2(source, target)

    shutil.copytree(root, destination, ignore=reject_links, copy_function=bounded_copy)


def _readiness(root: Path, scope: dict, day: str, batch_size: int):
    """Input: vault Path, original scope dict, date str, batch size int. Output: ReadinessReport. Keep the live strict gate."""
    return evaluate_run_readiness(root, mode="research", batch_size=batch_size,
                                  live_api_enabled=True, today_value=day, **scope)


class _CaptureClient:
    def __init__(self, client, deadline: float):
        """Input: GET/OPTIONS client and monotonic deadline float. Output: None. Track bounded factual fetches."""
        self.client = client
        self.deadline = deadline
        self.payloads = {}
        self.failures = []

    def _fetch(self, method: str, path: str):
        """Input: method/path str. Output: JSON payload. Enforce deadline, shape and complete single-page captures."""
        import time

        try:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("recovery deadline exhausted")
            self.client.timeout_seconds = min(TIMEOUT_SECONDS, remaining)
            payload = getattr(self.client, method)(path)
            if not isinstance(payload, (dict, list)):
                raise ValueError("invalid platform payload")
            if isinstance(payload, dict) and "results" in payload:
                rows = result_rows(payload)
                if not path.startswith("/data-sets?") and (payload.get("next") or int(payload.get("count", len(rows))) > len(rows)):
                    raise ValueError("incomplete bounded capture; pagination required")
            if path.startswith("/tutorial-pages/") and not payload.get("content"):
                raise ValueError("empty required rule content")
            self.payloads[path] = payload
            return payload
        except Exception as error:
            response = getattr(error, "response", None)
            self.failures.append({"path": path, "error": type(error).__name__,
                                  "status_code": getattr(response, "status_code", None)})
            raise

    def get_json(self, path: str):
        """Input: API path str. Output: JSON payload. Record one bounded GET."""
        return self._fetch("get_json", path)

    def options_json(self, path: str):
        """Input: API path str. Output: JSON payload. Record one bounded OPTIONS."""
        return self._fetch("options_json", path)


def _normalize_capture(path: Path, root: Path, endpoint: str) -> None:
    """Input: capture/root Paths and endpoint str. Output: None. Canonicalize provenance without helper globals."""
    metadata, body = parse_markdown_front_matter(path.read_text(encoding="utf-8"))
    metadata["source_path"] = path.relative_to(root).as_posix()
    metadata["source_endpoint"] = endpoint
    path.write_text(render_front_matter(metadata) + "\n" + body, encoding="utf-8")


def _validate_scope(tracked: _CaptureClient, scope: dict, instrument: str) -> dict:
    """Input: bounded client, exact scope dict and instrument str. Output: validation evidence dict. Probe settings and scoped datasets."""
    evidence = {"passed": False, "scope": scope, "instrument_type": instrument}
    field = "settings"
    try:
        options = tracked.options_json("/simulations")
        settings = options.get("actions", {}).get("POST", {}).get("settings", {})
        fields = settings.get("children", settings)
        for name, wanted in {"instrumentType": instrument, **scope}.items():
            field = name
            choices = fields.get(name, {}).get("choices", [])
            for dependency, selector in (("instrumentType", instrument), ("region", scope["region"]), ("delay", scope["delay"])):
                if not isinstance(choices, dict):
                    break
                if dependency in choices:
                    choices = choices[dependency]
                    if not isinstance(choices, dict):
                        raise ValueError("invalid choice dependency mapping")
                    choices = choices.get(str(selector), choices.get(selector, []))
                elif str(selector) in choices or selector in choices:
                    choices = choices.get(str(selector), choices.get(selector))
            if not isinstance(choices, list) or str(wanted) not in {
                str(item.get("value")) if isinstance(item, dict) else str(item) for item in choices
            }:
                raise ValueError("original scope unsupported by live simulation settings")
        field = "dataset"
        endpoint = "/data-sets?" + urlencode({"instrumentType": instrument, **scope, "limit": 1, "offset": 0})
        payload = tracked.get_json(endpoint)
        rows = result_rows(payload)
        if not rows:
            raise ValueError("no dataset in exact original scope")
        expected = {"instrumentType": instrument, "instrument_type": instrument, **scope}
        for row in rows:
            field = "dataset.id"
            if not isinstance(row.get("id"), str) or not row["id"].strip():
                raise ValueError("dataset probe requires a nonempty id")
            containers = [row]
            for container_name in ("scope", "settings"):
                if container_name in row:
                    field = "dataset." + container_name
                    if not isinstance(row[container_name], dict):
                        raise ValueError("dataset scope metadata must be an object")
                    containers.append(row[container_name])
            for container in containers:
                for name, wanted in expected.items():
                    field = "dataset." + name
                    if name in container and str(container[name]) != str(wanted):
                        raise ValueError("dataset probe scope mismatch")
        evidence.update({"passed": True, "dataset_endpoint": endpoint,
                         "dataset_probe_count": len(rows), "dataset_sample": rows[:1],
                         "field_recapture": False})
    except Exception as error:
        tracked.failures.append({"path": "/simulations+scoped-data-sets", "error": type(error).__name__,
                                 "field": field, "status_code": None})
    return evidence


def _capture_sources(root: Path, job: Path, now: str, tracked: _CaptureClient, scope: dict, instrument: str) -> dict:
    """Input: local Paths, ISO str and tracking client. Output: evidence dict. Capture raw sources with partial failures visible."""
    operators = []
    try:
        operators = result_rows(tracked.get_json("/operators"))
        if not operators or any(not row.get("name") for row in operators):
            tracked.failures.append({"path": "/operators", "error": "empty_or_invalid_operators", "status_code": None})
            operators = []
    except Exception:
        pass
    snapshot = refresh_incentive_snapshot(tracked, now)
    scope_validation = _validate_scope(tracked, scope, instrument)
    capture_dir = root / "raw/platform/learn" / now[:10] / job.name
    capture_dir.mkdir(parents=True)
    paths = []
    if "/simulations" in tracked.payloads:
        path = write_raw_rows("Original scope validation", "/simulations OPTIONS and scoped /data-sets GET",
                              [{"settings_options": tracked.payloads["/simulations"], **scope_validation}],
                              now, capture_dir, "scope_validation.md", ["machine/scope_matrix.jsonl"], root=root)
        _normalize_capture(path, root, "/simulations OPTIONS and scoped /data-sets GET")
        paths.append(path)
    if operators:
        path = write_raw_operators(operators, now, capture_dir, root=root)
        _normalize_capture(path, root, "/operators")
        paths.append(path)
    pages = [payload for endpoint, payload in tracked.payloads.items() if endpoint.startswith("/tutorial-pages/")]
    if pages:
        path = write_raw_documentation_pages(pages, now, capture_dir, root=root)
        _normalize_capture(path, root, "/tutorial-pages/{id}")
        paths.append(path)
    for endpoint, payload in tracked.payloads.items():
        if endpoint in {"/events?limit=50&offset=0", "/competitions?limit=50&offset=0"}:
            name = endpoint.split("?", 1)[0].strip("/")
            path = write_raw_rows(name, endpoint, result_rows(payload), now, capture_dir,
                                  name + ".md", ["machine/freshness_manifest.json"], root=root)
            _normalize_capture(path, root, endpoint)
            paths.append(path)
    warnings = [row for row in tracked.failures if row["path"] == OPTIONAL_RETIRED_PATH and row["status_code"] == 404]
    errors = [row for row in tracked.failures if row not in warnings]
    if tracked.failures:
        path = write_raw_errors(tracked.failures, now, capture_dir, root=root)
        _normalize_capture(path, root, "failed platform GET/OPTIONS")
        paths.append(path)
    activity_ok = not any(row["path"] not in {"/operators", "/simulations", "/simulations+scoped-data-sets"}
                          and not row["path"].startswith("/data-sets?") for row in errors)
    if activity_ok:
        # Keep the immutable snapshot separate from the compiler's legacy activity alias.
        path = write_raw_rows("Activity and rule snapshot", "platform incentive endpoints",
                              [asdict(snapshot)], now, capture_dir, "activity_snapshot.md",
                              ["machine/freshness_manifest.json"], root=root)
        _normalize_capture(path, root, "platform incentive endpoints")
        paths.append(path)
    immutable = job / "sources" / now[:10]
    immutable.mkdir(parents=True)
    for path in paths:
        shutil.copy2(path, immutable / path.name)
    return {"operators": operators, "activity_ok": activity_ok,
            "activity_path": (capture_dir / "activity_snapshot.md").relative_to(root).as_posix(),
            "warnings": warnings, "errors": errors,
            "operator_path": (capture_dir / "operators.md").relative_to(root).as_posix(),
            "scope_validation": scope_validation,
            "scope_path": (capture_dir / "scope_validation.md").relative_to(root).as_posix(),
            "sources": [str(immutable / path.name) for path in paths],
            "fetch_count": len(tracked.payloads), "operator_count": len(operators)}


def _restore_factual_contract(root: Path, original_manifest: list[dict], scopes: list[dict],
                              data_rows: list[dict], captured: dict, now: str, compiled: bool) -> None:
    """Input: local Path, original/captured dict rows, ISO str, compile bool. Output: None. Prevent factual date laundering."""
    manifest_path = root / "machine/freshness_manifest.json"
    current = json.loads(manifest_path.read_text(encoding="utf-8"))
    original = {row["name"]: row for row in original_manifest}
    restored = []
    for row in current:
        name = row["name"]
        old = original.get(name)
        if old:
            row = {**row, "updated_at": old["updated_at"], "max_age_days": old["max_age_days"]}
        elif name not in DERIVED_RESOURCES:
            row["updated_at"] = "1970-01-01"
        if name in DERIVED_RESOURCES and compiled:
            row["updated_at"] = now[:10]
            row["source_note"] = "Run-local regeneration/review; platform capture ages retained separately."
        if name == "data_ledger":
            days = [str(item.get("source_updated_at", "")) for item in data_rows]
            if days and all(len(day) == 10 for day in days):
                row["updated_at"] = min(days)
        if name == "operator_catalog" and captured["operators"]:
            row["updated_at"] = now[:10]
        if name == "activity_snapshot" and captured["activity_ok"]:
            row["updated_at"] = now[:10]
            row["path"] = captured["activity_path"]
        if name == "scope_matrix" and captured["scope_validation"]["passed"]:
            row["updated_at"] = now[:10]
            row["validated_scope"] = captured["scope_validation"]["scope"]
            row["source_note"] = "Run-local exact scope validation only; other scopes retain their factual capture ages."
            row["validation_source"] = captured["scope_path"]
        restored.append(row)
    # A compiler must not remove an existing policy record or global scope breadth.
    restored.extend(row for name, row in original.items() if name not in {r["name"] for r in restored})
    _write_json(manifest_path, restored)
    scope_path = root / "machine/scope_matrix.jsonl"
    # No new field captures occurred: preserve original breadth and factual row ages exactly.
    combined = scopes
    validation = captured["scope_validation"]
    if validation["passed"]:
        wanted = {"instrument_type": validation["instrument_type"], **validation["scope"]}
        matching = next((row for row in combined if all(row.get(name, "EQUITY" if name == "instrument_type" else None) == value
                                                       for name, value in wanted.items())), None)
        if matching is None:
            matching = dict(wanted)
            combined.append(matching)
        matching["validated_at"] = now
        matching["validation_source"] = captured["scope_path"]
        matching["validation_kind"] = "live_settings_and_dataset_probe_not_field_recapture"
    scope_path.write_text("".join(json.dumps(row, ensure_ascii=True) + "\n" for row in combined), encoding="utf-8")
    # The existing compiler only reads structured data-field operator captures, not Learn Markdown.
    operator_path = root / "machine/operator_ledger.jsonl"
    rows = _read_rows(operator_path)
    by_name = {row.get("operator"): row for row in rows}
    operator_source = captured["operator_path"]
    for operator in captured["operators"]:
        name = operator["name"]
        row = by_name.setdefault(name, {"operator": name, "family": operator.get("category", "unclassified")})
        row["source_paths"] = list(dict.fromkeys(row.get("source_paths", []) + [operator_source]))
    operator_path.write_text("".join(json.dumps(row, ensure_ascii=True) + "\n" for row in by_name.values()), encoding="utf-8")


def recover_knowledge(root: Path, config: dict, now: str, run_dir: Path, client=None) -> dict:
    """Input: vault/run Paths, original scope config dict, ISO str, optional GET client. Output: completed/blocked receipt dict.

    The caller must use returned knowledge_root for subsequent readiness and source binding.
    One attempt per run/root/scope/day/loaded-code-revision is durable, including failures and interruptions.
    No simulation, model call, final submission, cleanup or global vault publication occurs.
    """
    import time

    root = Path(root).resolve()
    run_dir = Path(run_dir).resolve()
    day = datetime.fromisoformat(now.replace("Z", "+00:00")).date().isoformat()
    scope = config.get("scope", config)
    frozen_path = run_dir / "runtime/original_batch_scope.json"
    if frozen_path.exists():
        scope = json.loads(frozen_path.read_text(encoding="utf-8"))["settings"]
    instrument = str(scope.get("instrumentType", scope.get("instrument_type", "EQUITY")))
    scope = {name: scope.get(name) for name in ("region", "delay", "universe")}
    revision = _source_code_revision()
    identity = {"root": str(root), "scope": scope, "instrument_type": instrument, "day": day,
                "batch_size": config.get("batch_size", 30), "source_code_revision": revision}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    job = run_dir / "runtime/knowledge_recovery" / key
    receipt_path = job / "receipt.json"
    staged = job / "knowledge"
    result = {"status": "blocked", "generated_at": now, "scope": scope,
              "source_code_revision": revision,
              "knowledge_root": str(staged), "effective_root": str(staged), "receipt_path": str(receipt_path),
              "warnings": [], "errors": [], "evidence": {}}
    if root == run_dir or root in run_dir.parents or run_dir in root.parents:
        result["errors"] = [{"error": "knowledge and run roots must be disjoint"}]
        return result
    job.parent.mkdir(parents=True, exist_ok=True)
    try:
        job.mkdir()
    except FileExistsError:
        if receipt_path.exists():
            try:
                previous = json.loads(receipt_path.read_text(encoding="utf-8"))
                if previous.get("phase") == "finished":
                    if previous.get("status") == "completed":
                        try:
                            report = _readiness(staged, scope, day, int(config.get("batch_size", 30)))
                            previous["evidence"]["readiness"] = asdict(report)
                            if not report.passed or report.blocked:
                                previous["status"] = "blocked"
                        except Exception as error:
                            previous["status"] = "blocked"
                            previous["errors"].append({"error": type(error).__name__, "stage": "cached_readiness"})
                        _write_json(receipt_path, previous)
                    return previous
            except (ValueError, OSError):
                pass
        result["errors"] = [{"error": "attempt already claimed or interrupted; do not repeat fetch"}]
        return result
    result["phase"] = "claimed"
    _write_json(receipt_path, result)
    try:
        if any(value is None for value in scope.values()):
            raise ValueError("original region/delay/universe required")
        _copy_vault(root, staged)
        original_manifest = json.loads((staged / "machine/freshness_manifest.json").read_text(encoding="utf-8"))
        scopes = _read_rows(staged / "machine/scope_matrix.jsonl")
        data_rows = _read_rows(staged / "machine/data_ledger.jsonl")
        transport = client if client is not None else WQBClient(timeout_seconds=TIMEOUT_SECONDS, max_retries=0, metrics_run_dir=run_dir)
        transport.max_retries = 0
        transport.timeout_seconds = TIMEOUT_SECONDS
        tracked = _CaptureClient(transport, time.monotonic() + MAX_RECOVERY_SECONDS)
        captured = _capture_sources(staged, job, now, tracked, scope, instrument)
        result["warnings"] = captured["warnings"]
        result["errors"] = captured["errors"]
        result["evidence"] = {name: captured[name] for name in ("sources", "fetch_count", "operator_count", "scope_validation")}
        result["phase"] = "captured"
        _write_json(receipt_path, result)
        compilation = {}
        try:
            compilation = run_knowledge_maintenance(staged, generated_at=now, apply_cleanup=False)
        finally:
            _restore_factual_contract(staged, original_manifest, scopes, data_rows, captured, now,
                                      compilation.get("status") == "completed")
        result["evidence"]["compile_status"] = compilation.get("status", "blocked")
        report = _readiness(staged, scope, day, int(config.get("batch_size", 30)))
        result["evidence"]["readiness"] = asdict(report)
        if report.passed and not report.blocked and not result["errors"] and compilation.get("status") == "completed":
            result["status"] = "completed"
    except Exception as error:
        result["errors"].append({"error": type(error).__name__, "stage": result["phase"]})
    result["phase"] = "finished"
    _write_json(receipt_path, result)
    return result
