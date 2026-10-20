from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from typing import Any


PROGRESS_FILES = ('planned_candidates.jsonl', 'simulation_events.jsonl', 'all_alphas.jsonl')
IDENTITY_FIELDS = ('expression_hash', 'child_index', 'parent_alpha_id', 'setting_variant',
                   'simulation_id', 'progress_url', 'alpha_id')
PROGRESS_CACHE_LIMIT = 16
PROGRESS_CACHE: dict[str, tuple[tuple, dict[str, Any]]] = {}
PROGRESS_LOCK = threading.Lock()


def _records(path: Path) -> list[dict[str, Any]]:
    """Input: Path. Output: list[dict]. Read complete local records, tolerating concurrent partial writes."""
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _match_score(existing: dict[str, Any], incoming: dict[str, Any]) -> int:
    """Input: two record dicts. Output: int. Match child identities without collapsing a shared parent URL."""
    shared = []
    for field in IDENTITY_FIELDS:
        left, right = existing.get(field), incoming.get(field)
        if left is None or right is None or left == '' or right == '':
            continue
        if left != right:
            return 0
        shared.append(field)
    if not any(field in shared for field in ('expression_hash', 'alpha_id', 'simulation_id')):
        return 0
    return len(shared)


def _project(source: Path, signature: tuple) -> dict[str, Any]:
    """Input: source Path and file signature tuple. Output: dict. Join plans, events, and checks by child identity."""
    joined: list[dict[str, Any]] = []
    for filename, mtime, _size in signature:
        updated = datetime.fromtimestamp(mtime / 1e9, timezone.utc).isoformat() if mtime else ''
        for incoming in _records(source / filename):
            candidates = [(index, _match_score(row, incoming)) for index, row in enumerate(joined)]
            candidates = [(index, score) for index, score in candidates if score]
            index = max(candidates, key=lambda item: (item[1], item[0]))[0] if candidates else len(joined)
            if index == len(joined):
                identity = json.dumps([str(source), incoming, index], sort_keys=True)
                joined.append({'key': hashlib.sha256(identity.encode()).hexdigest()[:20], 'status': 'planned'})
            row = joined[index]
            row.update({key: value for key, value in incoming.items() if value is not None})
            row['source_run_dir'] = str(source)
            row['updated_at'] = incoming.get('updated_at') or incoming.get('timestamp') or incoming.get('recorded_at') or updated
            event = str(incoming.get('event') or incoming.get('status', '')).upper()
            if event:
                row['status'] = {'SUBMITTED': 'running', 'CHECKED': 'checked', 'ERROR': 'error',
                                 'FAILED': 'error', 'PENDING': 'waiting'}.get(event, event.lower())
            if incoming.get('hard_pass') is True:
                row['status'] = 'qualified'
            row['metrics'] = incoming.get('metrics', row.get('metrics', {}))
            row['failures'] = incoming.get('failed', row.get('failures', []))
            if event in ('ERROR', 'FAILED') and incoming.get('message'):
                row['failures'] = [str(incoming['message'])]
            row['next_action'] = {'planned': '等待执行', 'running': '等待检查', 'waiting': '等待重试',
                                  'checked': '信号分流', 'qualified': '候选验证', 'error': '检查失败原因'}.get(row['status'], '等待状态更新')
    return {'source_run_dir': str(source), 'rows': joined,
            'counts': dict(Counter(row['status'] for row in joined))}


def load_strategy_progress(source_run_dir: str | Path | None) -> dict[str, Any]:
    """Input: bound source str/Path or None. Output: dict. Cache strategy projection by source artifact mtimes."""
    if source_run_dir is None:
        return {'source_run_dir': '', 'rows': [], 'counts': {}}
    source = Path(source_run_dir)
    tokens = []
    for name in PROGRESS_FILES:
        try:
            stat = (source / name).stat()
            tokens.append((name, stat.st_mtime_ns, stat.st_size))
        except OSError:
            tokens.append((name, 0, 0))
    signature = tuple(tokens)
    key = str(source.resolve())
    with PROGRESS_LOCK:
        cached = PROGRESS_CACHE.get(key)
        if cached and cached[0] == signature:
            return cached[1]
        result = _project(source, signature)
        if len(PROGRESS_CACHE) >= PROGRESS_CACHE_LIMIT:
            PROGRESS_CACHE.pop(next(iter(PROGRESS_CACHE)))
        PROGRESS_CACHE[key] = (signature, result)
        return result
