"""Read-only run-local authority audit; planning estimates are not permission or platform quota."""

import argparse
import json
from pathlib import Path

from wqb.runtime_control import runtime_authority_is_complete


def _read_object(path: Path, errors: list[str]) -> dict:
    """Input: JSON Path/error list. Output: dict. Read evidence without repairing or hiding corrupt files."""
    if not path.exists():
        return {}
    try:
        row = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(row, dict):
            return row
    except (OSError, ValueError):
        pass
    errors.append(str(path))
    return {}


def inspect_run_authority(run_dir: Path) -> dict:
    """Input: run Path. Output: report dict. Compare local permission and candidate evidence without granting authority."""
    run = Path(run_dir).resolve()
    errors = []
    control_path = run / 'runtime_control.json'
    control = _read_object(control_path, errors)
    worker = _read_object(run / 'runtime_status.json', errors)
    schedule = _read_object(run / 'stages' / 'schedule' / 'research_schedule.json', errors)
    binding = _read_object(run / 'stages' / 'scout_seed' / 'source_bridge_binding.json', errors)
    evidence = {'submitted_event_rows': 0, 'distinct_submitted_candidates': 0,
                'distinct_progress_urls': 0, 'checked_event_rows': 0, 'coverage': 'bound_source_only'}
    candidates, progress = set(), set()
    source_value = binding.get('source_run_dir')
    if source_value:
        source = Path(source_value).resolve()
        if not source.is_relative_to(run.parent) or not source.is_dir():
            errors.append('bound source is missing or outside the run root')
        else:
            events = source / 'simulation_events.jsonl'
            if not events.exists():
                errors.append(str(events))
            else:
                try:
                    with events.open(encoding='utf-8') as stream:
                        for number, line in enumerate(stream, 1):
                            if not line.strip():
                                continue
                            try:
                                row = json.loads(line)
                                if not isinstance(row, dict):
                                    raise ValueError('event must be an object')
                            except ValueError:
                                errors.append(f'{events}:{number}')
                                continue
                            if row.get('event') == 'SUBMITTED':
                                evidence['submitted_event_rows'] += 1
                                identity = row.get('simulation_identity_hash') or row.get('expression_hash')
                                if isinstance(identity, str) and identity:
                                    candidates.add(identity)
                                else:
                                    errors.append(f'{events}:{number}: missing candidate identity')
                                url = row.get('progress_url')
                                if isinstance(url, str) and url:
                                    progress.add(url)
                            elif row.get('event') == 'CHECKED':
                                evidence['checked_event_rows'] += 1
                except OSError:
                    errors.append(str(events))
    evidence.update(distinct_submitted_candidates=len(candidates), distinct_progress_urls=len(progress))
    maximum = control.get('max_simulations')
    used = worker.get('simulation_attempts', 0)
    valid = (runtime_authority_is_complete(control)
             and type(used) is int and used >= 0)
    status = 'runtime_authority_present' if valid else 'runtime_authority_required'
    if control_path.exists() and not valid:
        status = 'invalid_runtime_authority'
    if control.get('legacy_authority_required'):
        status = 'runtime_authority_required'
    if status == 'runtime_authority_present' and len(candidates) > used:
        status = 'accounting_reconciliation_required'
    if status == 'runtime_authority_present' and 'simulation_attempts' not in worker:
        status = 'accounting_reconciliation_required'
    if errors:
        status = 'invalid_runtime_authority' if str(control_path) in errors else 'evidence_invalid'
    return {'run_id': run.name, 'status': status, 'read_only': True,
            'planning_estimates': {key: schedule.get(key) for key in ('simulation_budget', 'api_budget')},
            'runtime_authority': {key: control.get(key) for key in
                                  ('desired_state', 'enable_live_api', 'max_simulations', 'request_revision')},
            'recorded_attempts': worker.get('simulation_attempts') if type(used) is int else None,
            'remaining_simulations': max(0, maximum - used) if status == 'runtime_authority_present' else None,
            'source_evidence': evidence, 'platform_quota': None, 'evidence_errors': errors,
            'limitations': ['Planning estimates are not enforced runtime limits or live authority.',
                            'Event rows, distinct candidates and progress URLs are different counts, not HTTP requests.',
                            'Bound-source evidence is not a complete account-wide or multi-stage quota ledger.',
                            'This audit never creates, repairs, resumes or adopts runtime authority.']}


def main() -> int:
    """Input: --run-dir CLI argument. Output: JSON/exit int. Inspect existing local evidence only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect_run_authority(args.run_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
