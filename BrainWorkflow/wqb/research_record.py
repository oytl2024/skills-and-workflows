from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from wqb.knowledge_contracts import (
    SourceIndexRow,
    render_front_matter,
    upsert_source_index_rows,
    parse_markdown_front_matter,
    _source_contract_path,
    _source_contract_bytes,
    verify_source_repair,
    _source_index_guard,
    _capture_json,
)
from wqb.knowledge_paths import machine_resource_path
from wqb.lockfile import json_lock_transition_guard


REPAIR_REPORT_TEXT_LIMIT = 240
REPAIR_REPORT_ATTEMPT_LIMIT = 12
REPAIR_REPORT_ITEM_LIMIT = 6
REPAIR_REPORT_CHAR_LIMIT = 24000
MANUAL_REPORT_MAX_BYTES = 64000
RECORD_LOCK_TIMEOUT_SECONDS = 5.0
RECORD_LOCK_SLEEP_SECONDS = 0.01


@dataclass(frozen=True)
class ResearchRecord:
    run_id: str
    objective: str
    backtest: list[dict[str, Any]] = field(default_factory=list)
    triage: list[dict[str, Any]] = field(default_factory=list)
    repair: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    candidate_gate: list[dict[str, Any]] = field(default_factory=list)
    user_approval: list[dict[str, Any]] = field(default_factory=list)
    approved_queue: list[dict[str, Any]] = field(default_factory=list)
    manual_submission_status: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failures(self) -> list[dict[str, Any]]:
        """Input: record. Output: triage rows. Preserve the legacy failures accessor."""
        return self.triage

    @property
    def alpha_results(self) -> list[dict[str, Any]]:
        """Input: record. Output: backtest rows. Preserve the legacy alpha-results accessor."""
        return self.backtest

    @property
    def repairs(self) -> dict[str, list[dict[str, Any]]]:
        """Input: record. Output: repair map. Preserve the legacy repairs accessor."""
        return self.repair

    @property
    def approvals(self) -> list[dict[str, Any]]:
        """Input: record. Output: approval rows. Preserve the legacy approvals accessor."""
        return self.user_approval

    @property
    def queue_updates(self) -> list[dict[str, Any]]:
        """Input: record. Output: queue rows. Preserve the legacy queue accessor."""
        return self.approved_queue


def empty_research_record(run_id: str, objective: str) -> ResearchRecord:
    """Input: run id and objective. Output: ResearchRecord. Create an empty research record."""
    return ResearchRecord(run_id=str(run_id), objective=str(objective))


def research_record_to_dict(record: ResearchRecord) -> dict[str, Any]:
    """Input: ResearchRecord. Output: dict. Convert a run record into a machine-ledger row."""
    return asdict(record)


def _research_record_final_state(record: ResearchRecord) -> str:
    """Input: ResearchRecord. Output: state label. Derive a compact run outcome for ledger filtering."""
    if record.manual_submission_status:
        return str(record.manual_submission_status[-1].get("status", "submitted"))
    if record.approved_queue:
        return str(record.approved_queue[-1].get("status", "approved_queue"))
    if record.candidate_gate:
        return "candidate_gate"
    if record.repair:
        return "repair"
    if record.backtest:
        return "in_progress"
    return "created"


def _case_reason(record: ResearchRecord) -> str:
    """Input: ResearchRecord. Output: case reason. Mark learning-worthy records for human case compilation."""
    if record.manual_submission_status or record.approved_queue:
        return "submitted_or_approved"
    if any(row.get("benchmark_label") == "near_miss" for row in record.triage):
        return "near_miss"
    if record.repair:
        return "repair_loop"
    if record.triage:
        return "representative_failure"
    return ""


def append_research_record_jsonl(
    knowledge_root: str | Path,
    record: ResearchRecord,
    synced_at: str,
) -> Path:
    """Input: knowledge root, record, timestamp. Output: machine JSONL path. Append a compact authoritative run row."""
    path = machine_resource_path(knowledge_root, "research_records")
    path.parent.mkdir(parents=True, exist_ok=True)
    row = research_record_to_dict(record) | {
        "synced_at": synced_at,
        "final_state": _research_record_final_state(record),
        "case_reason": _case_reason(record),
    }
    with json_lock_transition_guard(path, RECORD_LOCK_TIMEOUT_SECONDS, RECORD_LOCK_SLEEP_SECONDS,
                                    'research ledger is busy'):
        previous = path.read_text(encoding='utf-8') if path.exists() else ''
        # Validate before replacing; never repair away historical malformed evidence.
        for line in previous.splitlines():
            if line.strip():
                json.loads(line)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(previous + ('' if not previous or previous.endswith('\n') else '\n')
                             + json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
        temporary.replace(path)
    return path


def load_research_record_ledger(knowledge_root: str | Path) -> list[dict[str, Any]]:
    """Input: knowledge root. Output: research record rows. Load the machine research-record ledger."""
    path = machine_resource_path(knowledge_root, "research_records")
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sync_research_record_to_machine(
    record: ResearchRecord,
    knowledge_root: str | Path,
    synced_at: str | None = None,
) -> Path:
    """Input: record, knowledge root, timestamp. Output: machine path. Sync one research record into the machine ledger."""
    generated = synced_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return append_research_record_jsonl(knowledge_root, record, generated)


def record_alpha_result(record: ResearchRecord, alpha_row: dict[str, object]) -> ResearchRecord:
    """Input: record and alpha row. Output: updated record. Store alpha result with compact failure summaries."""
    row = _mechanism_record_row(alpha_row)
    results = [*record.backtest, row]
    triage = list(record.triage)
    if not bool(row.get("hard_pass", False)):
        triage.append(
            {
                "alpha_id": row.get("alpha_id", ""),
                "expression_hash": row.get("expression_hash", ""),
                "benchmark_label": row.get("benchmark_label", ""),
                "metrics": row.get("metrics", {}),
                "failed": row.get("failed", []),
            }
        )
    return replace(record, backtest=results, triage=triage)


def _mechanism_record_row(alpha_row: dict) -> dict:
    """Input: official generator result dict. Output: detached row joined to verified paired sidecar; no writes."""
    row = deepcopy(alpha_row)
    if not row.get('experiment_arms'):
        return row
    from wqb.generator import read_experiment_sidecar
    from wqb.hypothesis_selection import validate_operational_resource_context
    from wqb.cli import simulation_identity_hash
    receipt_path = Path(row['ai_plan_receipt'])
    receipt = json.loads(receipt_path.read_bytes())
    snapshot = receipt['config_patch']['hypothesis_snapshot']
    context = validate_operational_resource_context(snapshot)
    sidecar = read_experiment_sidecar(str(receipt_path), snapshot)
    identity = simulation_identity_hash(row['expression'], row['settings'])
    links = [link for link in sidecar['arms'] if link['expression_hash'] == identity]
    if identity != row.get('expression_hash') or not links or links != row['experiment_arms']:
        raise ValueError('research record paired arm identity mismatch')
    experiments = [e for e in sidecar['experiments'] if e['experiment_id'] in {link['experiment_id'] for link in links}]
    known = {e['experiment_id']: e for e in context['experiments']}
    for experiment in experiments:
        if experiment != known.get(experiment['experiment_id']):
            raise ValueError('research record experiment differs from frozen resources')
        for link in links:
            if link['experiment_id'] != experiment['experiment_id']:
                continue
            arm = next(a for a in experiment['arms'] if a['arm_id'] == link['arm_id'])
            if (arm['binding']['bound_expression'] != row['expression'] or arm['settings'] != row['settings']
                    or row.get('scope', arm['scope']) != arm['scope']):
                raise ValueError('research record expression/settings/scope differs from paired arm')
            row['scope'] = deepcopy(arm['scope'])
    row['mechanism_experiments'] = deepcopy(experiments)
    row['mechanism_reused_measurements'] = [deepcopy(link) for link in sidecar['arms']
        if link.get('reused') and link['experiment_id'] in {e['experiment_id'] for e in experiments}]
    row['mechanism_source'] = dict(manifest_sha256=sidecar['manifest_sha256'],
        sidecar_sha256=receipt['config_patch']['experiment_sidecar_sha256'])
    return row


def record_repair_version(
    record: ResearchRecord,
    candidate_id: str,
    version: int,
    expression_hash: str,
    hypothesis: str,
    result: dict[str, object],
) -> ResearchRecord:
    """Input: record and repair version. Output: updated record. Store one unique repair version."""
    repairs = {key: list(value) for key, value in record.repair.items()}
    rows = repairs.setdefault(str(candidate_id), [])
    identity = (int(version), str(expression_hash))
    if not any((int(row["version"]), str(row["expression_hash"])) == identity for row in rows):
        rows.append(
            {
                "candidate_id": str(candidate_id),
                "version": int(version),
                "expression_hash": str(expression_hash),
                "hypothesis": str(hypothesis),
                "result": dict(result),
            }
        )
    return replace(record, repair=repairs)


def record_repair_attempts(record: ResearchRecord, attempts: list[dict]) -> ResearchRecord:
    """Input: ResearchRecord, scheduler attempt dict list. Output: ResearchRecord with detached, resume-safe Repair evidence."""
    repairs = deepcopy(record.repair)
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        parent = str(attempt.get('parent_expression_hash') or attempt.get('parent_alpha_id') or '')
        if not parent:
            continue
        plan = attempt.get('plan') if isinstance(attempt.get('plan'), dict) else {}
        trace = attempt.get('experiment_trace')
        trace = trace if isinstance(trace, dict) else {}
        decision = trace.get('decision', plan.get('decision', {}))
        decision = decision if isinstance(decision, dict) else {}
        variants = plan.get('variants') or []
        children = attempt.get('children') or []
        child = trace.get('measured_child') or (children[0] if children else {})
        child = child if isinstance(child, dict) else {}
        variant = variants[0] if variants and isinstance(variants[0], dict) else {}
        provenance = {key: deepcopy(plan.get(key, '')) for key in ('evidence_digest', 'receipt_path')}
        # Plan identity excludes mutable phase/check/trace fields so a resumed measurement updates in place.
        identity = [attempt.get('parent_alpha_id', ''), parent, provenance,
                    [v.get('expression_hash', '') for v in variants if isinstance(v, dict)]]
        if not plan:
            identity.extend([attempt.get('source_run_dir', ''), attempt.get('actions', []),
                             child.get('expression_hash', '')])
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode('utf-8')).hexdigest()
        rows = repairs.setdefault(parent, [])
        existing = next((row for row in rows if row.get('attempt_digest') == digest), None)
        version = existing['version'] if existing is not None else max(
            (int(row.get('version', 0)) for row in rows), default=0) + 1
        row = {
            'candidate_id': parent, 'parent_alpha_id': str(attempt.get('parent_alpha_id', '')),
            'version': version,
            'expression_hash': str(child.get('expression_hash') or variant.get('expression_hash') or digest),
            'hypothesis': str(decision.get('hypothesis') or attempt.get('hypothesis') or ''),
            'result': deepcopy(child), 'attempt_digest': digest, 'plan_provenance': provenance,
            'stop_decision': bool(plan and plan.get('variants') == []),
        }
        if trace:
            row['experiment_trace'] = deepcopy(trace)
        if existing is None:
            rows.append(row)
        else:
            # An older/in-flight receipt must not erase an already measured trace on replay.
            if 'experiment_trace' not in row and 'experiment_trace' in existing:
                continue
            existing.update(row)
    return replace(record, repair=repairs)


def repair_report_text(value: Any) -> str:
    """Input: scalar object. Output: bounded escaped str, never a serialized ledger/container."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return 'not recorded'
    text = ' '.join(str(value).split())
    if len(text) > REPAIR_REPORT_TEXT_LIMIT:
        text = text[:REPAIR_REPORT_TEXT_LIMIT] + ' [truncated]'
    # Entities prevent HTML, links, inline code and table syntax from becoming active Markdown.
    return ''.join(f'&#{ord(char)};' if char in '&<>"\'\\`*_{}[]()|#!' else char for char in text) or 'not recorded'


def _repair_report_values(value: Any) -> str:
    """Input: scalar or list object. Output: str. Bound list summaries without dumping nested evidence."""
    if not isinstance(value, list):
        return repair_report_text(value)
    text = ', '.join(repair_report_text(item) for item in value[:REPAIR_REPORT_ITEM_LIMIT]) or 'none recorded'
    return text + (' [truncated]' if len(value) > REPAIR_REPORT_ITEM_LIMIT else '')


def _repair_change_text(baseline: dict, child: dict, decision: dict) -> str:
    """Input: measured row/decision dicts. Output: str. Describe observed edits without asserting control or causality."""
    if not child:
        return 'no measured child; no observed edit'
    before, after = baseline.get('settings'), child.get('settings')
    changes = []
    text = repair_report_text
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            if before.get(key) != after.get(key):
                changes.append(f'{text(key)}: {text(before.get(key))} -> {text(after.get(key))}')
                if len(changes) > 1:
                    return 'multiple observed changes; single-change isolation unverified'
    if baseline.get('expression') != child.get('expression'):
        changes.append(f"expression: {text(baseline.get('expression'))} -> {text(child.get('expression'))}")
    if len(changes) > 1:
        return 'multiple observed changes; single-change isolation unverified'
    if changes:
        return changes[0]
    return f"planned {text(decision.get('edit'))} -> {text(decision.get('value'))}; observed change unavailable"


def _bounded_repair_lines(lines: list[str]) -> list[str]:
    """Input: Markdown str list. Output: str list capped by total characters at line boundaries."""
    bounded: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) + 1 > REPAIR_REPORT_CHAR_LIMIT:
            return bounded + ['- Additional Repair evidence omitted [truncated].']
        bounded.append(line)
        size += len(line) + 1
    return bounded


def render_repair_report_lines(repairs: dict) -> list[str]:
    """Input: Repair map dict. Output: bounded Markdown str list shared by raw and compiled reports."""
    lines: list[str] = []
    count = 0
    if not isinstance(repairs, dict):
        return lines
    for parent, rows in repairs.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if count >= REPAIR_REPORT_ATTEMPT_LIMIT:
                return _bounded_repair_lines(lines + ['- Additional Repair attempts omitted [truncated].'])
            count += 1
            text = repair_report_text
            lines.extend([f"### {text(parent)} / version {text(row.get('version'))}",
                          f"- Hash: {text(row.get('expression_hash'))}"])
            provenance = row.get('plan_provenance', {})
            provenance = provenance if isinstance(provenance, dict) else {}
            lines.append(f"- Provenance: digest {text(provenance.get('evidence_digest'))}; receipt {text(provenance.get('receipt_path'))}")
            if row.get('stop_decision'):
                lines.append('- Stop decision: no variant or new measurement recorded.')
            trace = row.get('experiment_trace')
            if not isinstance(trace, dict) or trace.get('schema_version') != 1:
                lines.extend([f"- Hypothesis: {text(row.get('hypothesis'))}",
                              '- Trace unavailable: legacy or missing evidence; no measured outcome or authorship inferred.', ''])
                continue
            decision = trace.get('decision', {})
            decision = decision if isinstance(decision, dict) else {}
            baseline = trace.get('baseline', {})
            baseline = baseline if isinstance(baseline, dict) else {}
            child = trace.get('measured_child', {})
            child = child if isinstance(child, dict) else {}
            settings = baseline.get('settings', {})
            settings = settings if isinstance(settings, dict) else {}
            lines.extend([
                f"- Baseline: {text(baseline.get('alpha_id'))}; hash {text(baseline.get('expression_hash'))}; expression {text(baseline.get('expression'))}",
                f"- Baseline failed checks: {_repair_report_values(baseline.get('failed'))}",
                f"- Baseline scope: region: {text(settings.get('region'))}; universe: {text(settings.get('universe'))}; delay: {text(settings.get('delay'))}; period: {text(baseline.get('test_period', settings.get('testPeriod')))}",
                f"- Measured child: {text(child.get('alpha_id'))}; hash {text(child.get('expression_hash'))}",
                f"- Target: {text(decision.get('target_metric'))} / {text(decision.get('target_direction'))}; expected {text(decision.get('expected_improvement'))}",
                f"- Hypothesis: {text(decision.get('hypothesis'))}",
                f"- Economic rationale: {text(decision.get('economic_rationale'))}",
                f"- Single change: {_repair_change_text(baseline, child, decision)}",
            ])
            changes = trace.get('metric_changes', {})
            changes = changes if isinstance(changes, dict) else {}
            for metric, change in list(changes.items())[:REPAIR_REPORT_ITEM_LIMIT]:
                if isinstance(change, dict):
                    lines.append(f"- Before-after {text(metric)}: {text(change.get('before'))} -> {text(change.get('after'))}; delta {text(change.get('delta'))}")
            if len(changes) > REPAIR_REPORT_ITEM_LIMIT:
                lines.append('- Additional metrics omitted [truncated].')
            outcome = trace.get('outcome')
            lines.extend([
                f"- Outcome: {outcome if outcome in ('accept', 'reject', 'inconclusive') else 'inconclusive'}; {text(trace.get('reason'))}",
                f"- Limitations: risks {_repair_report_values(decision.get('risks'))}; remaining checks {_repair_report_values(trace.get('remaining_checks'))}",
                f"- Falsification: {text(decision.get('falsification'))}",
                f"- Applicability: {text(decision.get('applicability'))}",
                f"- Interpretation: {text(trace.get('interpretation'))}",
                '- Local measured comparison, not causal proof; not submission qualification.', '',
            ])
    return _bounded_repair_lines(lines)


def record_candidate_gate(record: ResearchRecord, candidate: dict[str, object], decision: str, reasons: list[str]) -> ResearchRecord:
    """Input: record, candidate, decision, reasons. Output: updated record. Store one gate decision."""
    row = dict(candidate)
    row["decision"] = str(decision)
    row["reasons"] = [str(item) for item in reasons]
    identity = _candidate_gate_identity(row)
    if any(_candidate_gate_identity(existing) == identity for existing in record.candidate_gate):
        return record
    return replace(record, candidate_gate=[*record.candidate_gate, row])


def record_approval(record: ResearchRecord, approval: dict[str, object]) -> ResearchRecord:
    """Input: record and approval. Output: updated record. Store user approval evidence."""
    identity = _candidate_identity(approval)
    if any(_candidate_identity(row) == identity for row in record.user_approval):
        return record
    return replace(record, user_approval=[*record.user_approval, dict(approval)])


def record_queue_update(record: ResearchRecord, queue_row: dict[str, object]) -> ResearchRecord:
    """Input: record and queue row. Output: updated record. Store approved queue update."""
    candidate_identity = _candidate_identity(queue_row)
    latest = next(
        (
            row
            for row in reversed(record.approved_queue)
            if _candidate_identity(row) == candidate_identity
        ),
        None,
    )
    if latest is not None and str(latest.get("status", "")) == str(queue_row.get("status", "")):
        return record
    return replace(record, approved_queue=[*record.approved_queue, dict(queue_row)])


def record_manual_submission_status(record: ResearchRecord, status_row: dict[str, object]) -> ResearchRecord:
    """Input: record and status row. Output: updated record. Store manual or API submission queue status."""
    candidate_identity = _candidate_identity(status_row)
    latest = next(
        (
            row
            for row in reversed(record.manual_submission_status)
            if _candidate_identity(row) == candidate_identity
        ),
        None,
    )
    if latest is not None and str(latest.get("status", "")) == str(status_row.get("status", "")):
        return record
    return replace(
        record,
        manual_submission_status=[*record.manual_submission_status, dict(status_row)],
    )


def _candidate_identity(row: dict[str, object]) -> tuple[str, str, str, str, str]:
    """Input: approval or queue row. Output: exact candidate identity. Normalize durable record keys."""
    return (
        str(row.get("candidate_id", "")),
        str(row.get("platform_alpha_id", "")),
        str(row.get("version", "")),
        str(row.get("expression_hash", "")),
        str(row.get("source_run_id", "")),
    )


def _candidate_gate_identity(row: dict[str, object]) -> tuple[str, str, str, str, str, str]:
    """Input: candidate-gate row. Output: full gate identity. Include decision for idempotent gate records."""
    return (*_candidate_identity(row), str(row.get("decision", "")))


def write_research_record(path: str | Path, record: ResearchRecord) -> Path:
    """Input: path and record. Output: written path. Persist machine-readable research record."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(
        json.dumps(asdict(record), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp.replace(target)
    return target


def load_research_record(path: str | Path) -> ResearchRecord:
    """Input: path. Output: ResearchRecord. Load a machine-readable research record."""
    row = json.loads(Path(path).read_text(encoding="utf-8"))
    return ResearchRecord(
        run_id=str(row["run_id"]),
        objective=str(row.get("objective", "")),
        backtest=list(row.get("backtest", row.get("alpha_results", []))),
        triage=list(row.get("triage", row.get("failures", []))),
        repair=dict(row.get("repair", row.get("repairs", {}))),
        candidate_gate=list(row.get("candidate_gate", [])),
        user_approval=list(row.get("user_approval", row.get("approvals", []))),
        approved_queue=list(row.get("approved_queue", row.get("queue_updates", []))),
        manual_submission_status=list(row.get("manual_submission_status", [])),
    )


def render_research_record_markdown(record: ResearchRecord) -> str:
    """Input: record. Output: Markdown. Render research findings for raw knowledge sync."""
    lines = [
        "# Research Record",
        "",
        f"- Run ID: `{record.run_id}`",
        f"- Objective: {record.objective}",
        "",
        "## Backtest",
    ]
    for row in record.backtest:
        lines.append(f"- `{row.get('alpha_id', '')}` `{row.get('expression_hash', '')}`")
    lines.extend(["", "## Triage", ""])
    for row in record.triage:
        lines.append(f"- `{row.get('alpha_id', '')}` {row.get('decision', row.get('benchmark_label', ''))}")
    lines.extend(["", "## Repair", ""])
    lines.extend(render_repair_report_lines(record.repair))
    lines.extend(["", "## Candidate Gate", ""])
    for row in record.candidate_gate:
        lines.append(f"- `{row.get('candidate_id', '')}` {row.get('decision', '')}: {', '.join(row.get('reasons', []))}")
    lines.extend(["", "## User Approval", ""])
    for row in record.user_approval:
        lines.append(f"- `{row.get('candidate_id', '')}` hash `{row.get('expression_hash', '')}`")
    lines.extend(["", "## Approved Queue", ""])
    for row in record.approved_queue:
        lines.append(f"- `{row.get('candidate_id', '')}` status `{row.get('status', '')}`")
    lines.extend(["", "## Manual Submission Status", ""])
    for row in record.manual_submission_status:
        lines.append(f"- `{row.get('candidate_id', '')}` status `{row.get('status', '')}`")
        if row.get('evidence_kind') == 'direct_user_report':
            lines.extend(['', '```json', json.dumps(row, ensure_ascii=True, sort_keys=True), '```',
                          'User report only; historical checks unchanged; submission timestamp unknown.'])
    return "\n".join(lines) + "\n"


def sync_research_record_to_raw(record: ResearchRecord, raw_root: str | Path) -> Path:
    """Input: record and raw root. Output: Markdown path. Write raw research record into knowledge raw."""
    raw = Path(raw_root)
    knowledge_root = raw.parent
    path = raw / "research" / "runs" / record.run_id / "research_record.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = render_research_record_markdown(record)
    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    relative_path = path.relative_to(knowledge_root).as_posix()
    metadata = {
        "source_type": "workflow_research_record",
        "source_family": "raw/research/runs",
        "source_path": relative_path,
        "captured_at": captured_at,
        "capture_tool": "wqb.research_record",
        "content_status": "raw_markdown",
        "record_count": 1,
        "content_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "update_check": "sync after workflow state changes",
        "compiled_targets": [
            "machine/research_records.jsonl",
            "wiki/60_research_cases",
        ],
    }
    if path.exists():
        previous_metadata, previous_body = parse_markdown_front_matter(path.read_text(encoding='utf-8'))
        if previous_body == body and all(previous_metadata.get(key) == value for key, value in metadata.items()
                                         if key != 'captured_at'):
            metadata['captured_at'] = previous_metadata['captured_at']
    content = render_front_matter(metadata) + body
    if not path.exists() or path.read_text(encoding='utf-8') != content:
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(path)
    upsert_source_index_rows(
        knowledge_root,
        [
            SourceIndexRow(
                path=relative_path,
                source_family="raw/research/runs",
                source_type="workflow_research_record",
                contents=f"Workflow research record for {record.run_id}.",
                update_check="sync after workflow state changes",
                captured_at=str(metadata["captured_at"]),
                record_count=int(metadata["record_count"]),
                content_hash=str(metadata["content_hash"]),
                content_status=str(metadata["content_status"]),
                compiled_targets=[
                    "machine/research_records.jsonl",
                    "wiki/60_research_cases",
                ],
            )
        ],
    )
    return path


def _verified_manual_report(root: Path, report_path: Path) -> tuple[str, dict]:
    """Input: vault/report Paths. Output: (Alpha str, provenance dict). Verify indexed direct-report bytes, never platform status."""
    relative = report_path.absolute().relative_to(root.absolute()).as_posix()
    if not relative.startswith('raw/community/user_messages/') or report_path.suffix != '.md':
        raise ValueError('manual submission requires a raw community user report')
    path = _source_contract_path(root, relative)
    raw = _source_contract_bytes(path, MANUAL_REPORT_MAX_BYTES)
    metadata, body = parse_markdown_front_matter(raw.decode('utf-8').replace('\r\n', '\n'))
    index = _source_contract_path(root, 'machine/source_index.jsonl')
    rows = [_capture_json(line.encode('utf-8')) for line in index.read_text(encoding='utf-8').splitlines() if line.strip()]
    matches = [row for row in rows if row.get('path') == relative]
    if len(matches) != 1:
        raise ValueError('manual report index missing or ambiguous')
    row = matches[0]
    for key in ('source_type', 'source_family', 'captured_at', 'content_hash', 'content_status', 'record_count'):
        if metadata.get(key) != row.get(key):
            raise ValueError('manual report metadata/index mismatch: ' + key)
    if (metadata.get('source_type') != 'user_report' or metadata.get('source_family') != 'raw/community/user_messages'
            or metadata.get('capture_tool') != 'codex_user_report' or metadata.get('source_path') != relative
            or metadata.get('record_count') != 1 or metadata.get('content_status') != 'raw_markdown'
            or hashlib.sha256(body.encode('utf-8')).hexdigest() != row.get('content_hash')):
        raise ValueError('manual report source contract mismatch')
    datetime.fromisoformat(str(metadata['captured_at']).replace('Z', '+00:00'))
    proof = verify_source_repair(root, relative)
    digest = hashlib.sha256(raw).hexdigest()
    if proof.get('status') not in ('verified', 'not_repaired') or proof.get('source_sha256') != digest:
        raise ValueError('manual report original bytes changed')
    headings = re.findall(r'^# Manual Submission Report: ([A-Za-z0-9]+)$', body, re.MULTILINE)
    statements = re.findall(r'^The user reports that Alpha ([A-Za-z0-9]+) was manually submitted\.$', body, re.MULTILINE)
    if len(headings) != 1 or statements != headings:
        raise ValueError('manual report assertion absent or ambiguous')
    return headings[0], {'report_path': relative, 'report_sha256': digest,
                         'content_hash': row['content_hash'], 'captured_at': row['captured_at']}


def _manual_local_identity(run: Path, record: ResearchRecord, alpha_id: str) -> dict:
    """Input: run Path, ResearchRecord, Alpha str. Output: exact verified identity dict; reject absent/conflicting local evidence."""
    from wqb.repair_identity import identity_hash_scheme
    local = [_capture_json(line.encode('utf-8')) for line in (run / 'all_alphas.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in record.backtest):
        raise ValueError('malformed research record backtest row')
    groups = [[row for row in rows if row.get('alpha_id') == alpha_id] for rows in (local, record.backtest)]
    if any(not rows for rows in groups):
        raise ValueError('Alpha missing from local results or research record')
    identities = []
    for row in [item for rows in groups for item in rows]:
        if not identity_hash_scheme(row):
            raise ValueError('unverified local expression/settings hash')
        identities.append({key: row[key] for key in ('alpha_id', 'expression', 'expression_hash', 'settings')})
    encoded = [json.dumps(identity, sort_keys=True, allow_nan=False) for identity in identities]
    if len(set(encoded)) != 1:
        raise ValueError('ambiguous local Alpha/expression/settings identity')
    return identities[0]


def _project_manual_queue(run: Path, identity: dict, reported_at: str) -> tuple[list[str], list[str]]:
    """Input: run Path, identity dict, report-time str. Output: paths/diagnostics lists. Update only an existing compatible queue row."""
    from wqb.candidate_queue import QUEUE_FILENAME, load_approved_queue, update_candidate_queue_status
    path = run / QUEUE_FILENAME
    if not path.exists():
        return [], ['candidate queue absent; no approval or queue created']
    matches = [row for row in load_approved_queue(run) if row.get('platform_alpha_id') == identity['alpha_id']]
    if len(matches) != 1:
        return [], ['candidate queue unresolved: matching row absent or ambiguous']
    row = matches[0]
    if row.get('expression_hash') != identity['expression_hash'] or row.get('source_run_id') != run.name:
        return [], ['candidate queue unresolved: immutable identity mismatch']
    if ('settings' in row and row['settings'] != identity['settings']) or ('expression' in row and row['expression'] != identity['expression']):
        return [], ['candidate queue unresolved: expression/settings mismatch']
    if row.get('status') in ('api_submitted', 'invalidated'):
        return [], ['candidate queue retained: existing terminal status']
    update_candidate_queue_status(run, row['candidate_id'], row['version'], row['expression_hash'],
                                  'manually_submitted', reported_at)
    return [str(path)], []


def reconcile_manual_submission(knowledge_root: Path, run_dir: Path, report_path: Path, reported_at: str) -> dict:
    """Input: vault/run/report Paths, report-time str. Output: status/identity/provenance/projections/diagnostics dict. Reconcile locally, never approve, recheck or submit."""
    from wqb.candidate_evidence import invalidate_self_pool
    from wqb.data_ledger_compile import project_manual_submission_usage
    from wqb.source_run_lock import acquire_source_run_lock, release_source_run_lock
    root, run = Path(knowledge_root), Path(run_dir)
    result = dict(status='blocked', alpha_id=None, identity=None, provenance=None, projection_paths=[], diagnostics=[])
    lock = None
    now = datetime.now(timezone.utc).isoformat()
    durable = False
    try:
        timestamp = datetime.fromisoformat(reported_at.replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('reported_at requires a timezone')
        alpha_id, provenance = _verified_manual_report(root, Path(report_path))
        result.update(alpha_id=alpha_id, provenance=provenance)
        # The normal source lock excludes operation writers without modifying runtime intent or authority.
        lock = acquire_source_run_lock(run, 'reconcile_manual_submission', now)
        if lock.get('status') != 'acquired':
            raise ValueError('source run mutation lock is busy')
        path = run / 'research_record.json'
        record = load_research_record(path)
        if record.run_id != run.name:
            raise ValueError('research record run identity mismatch')
        identity = _manual_local_identity(run, record, alpha_id)
        result['identity'] = identity
        if any(not isinstance(row, dict) for row in record.manual_submission_status):
            raise ValueError('malformed manual submission lifecycle row')
        prior = [row for row in record.manual_submission_status
                 if row.get('evidence_kind') == 'direct_user_report' and row.get('platform_alpha_id') == alpha_id]
        if any(row.get('identity') != identity for row in prior):
            raise ValueError('manual submission lifecycle identity conflict')
        with _source_index_guard(root):
            if _verified_manual_report(root, Path(report_path)) != (alpha_id, provenance):
                raise ValueError('manual report changed before lifecycle commit')
            invalidate_self_pool(root, 'manual_submission:' + alpha_id)
            if not prior:
                event = dict(platform_alpha_id=alpha_id, expression_hash=identity['expression_hash'], source_run_id=record.run_id,
                             status='manually_submitted', identity=identity, provenance=provenance,
                             reported_at=reported_at, submitted_at=None, evidence_kind='direct_user_report')
                record = replace(record, manual_submission_status=[*record.manual_submission_status, event])
                write_research_record(path, record)
        durable = True
        result['projection_paths'].append(str(path))
        rows = load_research_record_ledger(root)
        expected = research_record_to_dict(record)
        latest = next((row for row in reversed(rows) if row.get('run_id') == record.run_id), {})
        if any(latest.get(key) != value for key, value in expected.items()):
            ledger_path = sync_research_record_to_machine(record, root, reported_at)
        else:
            ledger_path = machine_resource_path(root, 'research_records')
        result['projection_paths'].append(str(ledger_path))
        result['projection_paths'].append(str(sync_research_record_to_raw(record, root / 'raw')))
        usage = project_manual_submission_usage(root, record.manual_submission_status, reported_at)
        result['projection_paths'].extend(usage['projection_paths'])
        result['diagnostics'].extend(usage['diagnostics'])
        queue_paths, diagnostics = _project_manual_queue(run, identity, reported_at)
        result['projection_paths'].extend(queue_paths)
        result['diagnostics'].extend(diagnostics)
        result['status'] = 'reconciled'
    except (OSError, ValueError, TypeError, KeyError) as error:
        result['status'] = 'partial' if durable else 'blocked'
        result['diagnostics'].append(f'{type(error).__name__}: {error}')
    finally:
        if lock and lock.get('status') == 'acquired':
            release_source_run_lock(run, 'reconcile_manual_submission', now, owner_id=lock.get('owner_id'))
    return result
