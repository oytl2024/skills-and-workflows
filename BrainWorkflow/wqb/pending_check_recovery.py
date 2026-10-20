"""Recover checks for existing Alpha identities without submitting simulations."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wqb.stage_outcomes import checked_research_rows, research_benchmark_label
from wqb.runtime_control import _write


MAX_CHECK_RECOVERY_ROWS = 30
MAX_CHECK_ATTEMPTS = 3
CHECK_PENDING_RETRY_SECONDS = 60
CHECK_RECOVERY_RECEIPT = 'stages/backtest/check_recovery.json'


def recover_pending_checks(root: Path, fetch) -> dict:
    """Input: run Path and (alpha_id:str)->CheckSummary callable. Output: receipt dict. Journal bounded checks and publish atomically."""
    path = root / CHECK_RECOVERY_RECEIPT
    data = root / 'all_alphas.jsonl'
    digest = hashlib.sha256(data.read_bytes()).hexdigest()
    receipt = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if receipt:
        if receipt.get('run_id') != root.name:
            raise ValueError('check recovery belongs to another run')
        if digest == receipt.get('output_sha256') and receipt.get('status') == 'prepared':
            receipt['status'] = receipt.get('publish_status', 'completed')
            _write(path, receipt)
        if digest == receipt.get('output_sha256') and receipt.get('status') == 'completed':
            return receipt
        if digest not in {receipt.get('input_sha256'), receipt.get('publication_input_sha256'), receipt.get('output_sha256')}:
            raise ValueError('check recovery input changed; preserve evidence')
        if receipt.get('rate_limit_retry_at') and receipt.get('status') == 'paused':
            if datetime.now(timezone.utc) < datetime.fromisoformat(receipt['rate_limit_retry_at']):
                return receipt
    else:
        rows = checked_research_rows(root)
        targets = [row for row in rows if research_benchmark_label(row, root) == 'pending_review']
        if not rows or not targets or len(targets) > MAX_CHECK_RECOVERY_ROWS:
            raise ValueError('bounded checked identities required for check recovery')
        receipt = {'run_id': root.name, 'input_sha256': digest, 'rows': rows,
                   'target_ids': [row['alpha_id'] for row in targets], 'results': {}, 'attempts': {}, 'status': 'running'}
        _write(path, receipt)
    for row in receipt['rows']:
        identity = row['alpha_id']
        if identity not in receipt['target_ids']:
            continue
        saved = receipt['results'].get(identity)
        if saved is not None and research_benchmark_label(saved, root) != 'pending_review':
            continue
        attempts = receipt.setdefault('attempts', {}).get(identity, 0)
        if attempts >= MAX_CHECK_ATTEMPTS:
            continue
        summary = fetch(identity)
        if summary.alpha_id != identity:
            raise ValueError('check recovery returned another Alpha identity')
        receipt['results'][identity] = {**row, 'hard_pass': summary.hard_pass,
            'failed': [item.name for item in summary.failed],
            'pending': [item.name for item in summary.pending],
            'warnings': [item.name for item in summary.warnings], 'metrics': summary.metrics}
        receipt['attempts'][identity] = attempts + 1
        _write(path, receipt)
    rows = [receipt['results'].get(row['alpha_id'], row) for row in receipt['rows']]
    output = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode('utf-8')
    if hashlib.sha256(data.read_bytes()).hexdigest() != digest:
        raise ValueError('checked research changed while recovering checks')
    pending = [row for row in rows if research_benchmark_label(row, root) == 'pending_review']
    retryable = bool(pending) and any(receipt['attempts'].get(row['alpha_id'], 0) < MAX_CHECK_ATTEMPTS for row in pending)
    receipt.update(status='prepared', publication_input_sha256=digest,
                   publish_status='paused' if pending else 'completed',
                   blocker='existing Alpha checks remain pending' if pending else '',
                   recovery_eligible=retryable,
                   rate_limit_retry_at=(datetime.now(timezone.utc) + timedelta(seconds=CHECK_PENDING_RETRY_SECONDS)).isoformat() if retryable else '',
                   rate_limit_source_run_dir=str(root / 'stages/backtest/checks') if retryable else '',
                   output_sha256=hashlib.sha256(output).hexdigest())
    _write(path, receipt)
    temporary = data.with_suffix('.recovery.tmp')
    temporary.write_bytes(output)
    temporary.replace(data)
    receipt['status'] = receipt['publish_status']
    _write(path, receipt)
    return receipt
