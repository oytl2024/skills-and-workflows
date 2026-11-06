"""Read-only execution boundary for positively identified historical AI Repair."""

import json
from pathlib import Path


def discover_retirement_aware_workflow(run_root: Path):
    """Input: runs root Path. Output: WorkflowStateDiscovery. Read active identity without reviving retired siblings."""
    from wqb.workflow_state import (
        discover_active_workflow, load_active_run, _load_discovery_state,
        TERMINAL_RUN_STATUSES, WorkflowStateDiscovery,
        blocking_terminal_issues, diagnose_state_consistency,
    )
    root = Path(run_root).resolve()
    try:
        if root.exists():
            for run in root.iterdir():
                if run.is_symlink() or run.is_junction():
                    return WorkflowStateDiscovery(None, run, run.name, ['linked_run_directory'])
    except OSError:
        return WorkflowStateDiscovery(None, root, '', ['run_directory_unreadable'])
    fallback = discover_active_workflow(run_root)
    if fallback.diagnostics != ['multiple_active_runs']:
        return fallback
    try:
        pointer = load_active_run(root)
        selected = Path(pointer['run_dir'])
        if selected.resolve().parent != root or selected.name != pointer['run_id']:
            return fallback
        # Retain a valid pointer location so read models cannot hide ambiguous live runs as absent.
        fallback = WorkflowStateDiscovery(None, selected, pointer['run_id'], fallback.diagnostics)
        selected_boundary = retirement_boundary(selected)
        chosen = None
        for run in root.iterdir():
            if run.is_symlink() or run.is_junction():
                return WorkflowStateDiscovery(None, run, run.name, ['linked_run_directory'])
            if not run.is_dir():
                continue
            boundary = selected_boundary if run.resolve() == selected.resolve() else retirement_boundary(run)
            if boundary is not None and boundary['status'] == 'retired':
                if run.resolve() == selected.resolve():
                    state, _, _ = _load_discovery_state(root, run)
                    chosen = WorkflowStateDiscovery(state, run, run.name, [])
                continue
            if selected_boundary is not None:
                # Never project an ambiguous retired pointer as permission for another Start.
                fallback = WorkflowStateDiscovery(None, run, run.name, fallback.diagnostics)
            if boundary is not None:
                return fallback
            state, issue, recovered = _load_discovery_state(root, run)
            if issue not in {'', 'run_state_missing'}:
                return fallback
            if state is None:
                continue
            if state.status in TERMINAL_RUN_STATUSES:
                if blocking_terminal_issues(state, diagnose_state_consistency(run, state)):
                    return fallback
                continue
            if run.resolve() != selected.resolve() or recovered:
                return fallback
            if state.run_id != pointer['run_id'] or Path(state.run_dir).resolve() != selected.resolve():
                return fallback
            chosen = WorkflowStateDiscovery(state, run, state.run_id, [])
        return chosen or fallback
    except (OSError, ValueError, KeyError, TypeError):
        return fallback


def retirement_boundary(run: Path) -> dict | None:
    """Input: owning run Path. Output: boundary dict or None. Inspect local frozen authority without migration."""
    run = Path(run)
    try:
        manifest_path = _local_path(run, 'run_manifest.json')
        missing_manifest = not manifest_path.exists()
        manifest = {} if missing_manifest else json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(manifest, dict):
            raise ValueError('manifest must be an object')
        if manifest.get('run_id', run.name) != run.name:
            raise ValueError('manifest run identity mismatch')
        snapshot = manifest.get('start_snapshot', {})
        if not isinstance(snapshot, dict):
            raise ValueError('start_snapshot must be an object')
        policy = snapshot.get('research_policy', {})
        if not isinstance(policy, dict):
            raise ValueError('research_policy must be an object')
        deterministic = policy.get('deterministic_repair', False)
        if type(deterministic) is not bool:
            raise ValueError('deterministic_repair must be boolean')
    except (OSError, ValueError, UnicodeError) as error:
        return _boundary(run, 'damaged', f'invalid frozen manifest: {error}', ['run_manifest.json'])
    if deterministic:
        return None
    evidence = ['run_manifest.json#start_snapshot.research_policy.deterministic_repair=false'] if 'deterministic_repair' in policy else []
    try:
        receipt_path = _local_path(run, 'stages/repair/repair_execution.json')
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            if not isinstance(receipt, dict):
                raise ValueError('Repair receipt must be an object')
            if receipt.get('run_id', run.name) != run.name:
                raise ValueError('Repair receipt identity mismatch')
            for attempt in receipt.get('attempts', []):
                judgment = attempt.get('plan', {}).get('judgment', {})
                if isinstance(judgment.get('checkpoint_id'), str) and judgment['checkpoint_id'].strip():
                    evidence.append('stages/repair/repair_execution.json')
                    break
        checkpoint_path = _local_path(run, 'stages/ai/ai_checkpoints.jsonl')
        if checkpoint_path.exists():
            for line in checkpoint_path.read_text(encoding='utf-8').splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get('checkpoint_type') in {'near_miss_interpretation', 'repair_decision'} and row.get('checkpoint_id'):
                    evidence.append('stages/ai/ai_checkpoints.jsonl')
                    break
        decisions = _local_path(run, 'runtime/repair_decisions')
        if decisions.exists():
            for path in sorted(decisions.glob('*.json')):
                path = _local_path(run, str(path.relative_to(run)))
                if path.name.endswith(('.input.json', '.support.json')):
                    continue
                decision = json.loads(path.read_text(encoding='utf-8'))
                judgment = decision.get('judgment', {})
                if isinstance(judgment, dict) and judgment.get('checkpoint_id'):
                    evidence.append(path.relative_to(run).as_posix())
                    break
    except (OSError, ValueError, UnicodeError, TypeError, AttributeError) as error:
        return _boundary(run, 'damaged', f'invalid historical Repair evidence: {error}', ['run_manifest.json'])
    if evidence:
        if missing_manifest:
            return _boundary(run, 'damaged', 'frozen manifest missing for persisted AI Repair evidence', evidence)
        return _boundary(run, 'retired', 'legacy model-driven AI Repair execution is retired; evidence is read-only',
                         ['run_manifest.json', *evidence])
    return None


def _local_path(run: Path, relative: str) -> Path:
    """Input: owning Path and relative str. Output: safe Path. Reject linked or escaping local evidence."""
    path = run / relative
    root = run.resolve()
    if not path.resolve().is_relative_to(root):
        raise ValueError('retirement evidence escapes owning run')
    for component in (run, *path.relative_to(run).parents):
        candidate = component if component == run else run / component
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError('linked retirement evidence is not allowed')
    if path.is_symlink() or path.is_junction():
        raise ValueError('linked retirement evidence is not allowed')
    return path


def _boundary(run: Path, status: str, reason: str, evidence: list[str]) -> dict:
    """Input: run Path, status/reason strs, evidence list. Output: dict. Project a nonexecuting boundary."""
    return dict(active=True, run_id=run.name, run_dir=str(run), status=status,
                next_action='workflow-start' if status == 'retired' else '',
                pause_reason=reason, runtime_status='blocked', runtime_reason=reason,
                read_only=True, can_start=status == 'retired', can_resume=False, waiting_for_user=False,
                diagnostics=[reason], consistent=status == 'retired',
                retirement={'classification': status, 'evidence_paths': evidence})
