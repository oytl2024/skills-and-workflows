"""Script-owned terminal package collection, preserving authority and lossless history."""
from contextlib import ExitStack
from datetime import datetime
import os
import re
from pathlib import Path

from wqb.execution_package import _digest, _read, _root
from wqb.execution_package_storage import (
    ARCHIVE_INDEX, MAX_LOCAL_INPUT_BYTES, _bytes, _owner_seal,
    load_package_archive, prepare_package_archive, read_archived_input,
)
from wqb.exploration_eligibility import _store_immutable
from wqb.lockfile import json_lock_transition_guard
from wqb.semantic_compilation import _safe


SUMMARY_ROOT = 'runtime/execution_package/retirement_summaries/'
RETIRED_RECEIPT = 'runtime/execution_package/retired.json'
COLLECTION_RECEIPT = 'runtime/execution_package/collected.json'
LOCK_SECONDS = 5.0
LOCK_POLL_SECONDS = .05


def load_retired_summary(run: Path) -> dict:
    """Input: owning run Path. Output: verified historical summary; no execution or current check permission."""
    run = _root(run)
    try:
        seal, seal_hash = _owner_seal(run)
        receipt, _ = _read(run, RETIRED_RECEIPT)
        if not re.fullmatch(r'runtime/execution_package/retirement_summaries/[0-9a-f]{64}\.json',
                            receipt.get('summary_path', '')):
            raise ValueError('invalid retired summary selector')
        summary, summary_hash = _read(run, receipt['summary_path'])
        archive = load_package_archive(run)
        _, archive_hash = _read(run, ARCHIVE_INDEX)
        if (set(receipt) != {'schema_version', 'kind', 'run_id', 'retired_at', 'seal_sha256',
                'summary_path', 'summary_sha256', 'archive_sha256', 'proof_path', 'proof_sha256', 'content_sha256'}
                or type(receipt['schema_version']) is not int or receipt['schema_version'] != 1
                or receipt['kind'] != 'retired_execution_package' or receipt['run_id'] != run.name
                or receipt['seal_sha256'] != seal_hash or receipt['summary_sha256'] != summary_hash
                or receipt['archive_sha256'] != archive_hash
                or receipt['content_sha256'] != _digest({k: v for k, v in receipt.items() if k != 'content_sha256'})
                or summary['run_id'] != run.name or summary['authority']['manifest_sha256'] != seal['manifest_sha256']
                or summary['authority']['snapshot_sha256'] != seal['snapshot_sha256']
                or summary['authority_changed'] is not False or summary['grants_final_submission_authority'] is not False
                or receipt['summary_path'] != SUMMARY_ROOT + _digest(summary) + '.json'
                or archive['run_id'] != run.name):
            raise ValueError('retired package receipt or summary changed')
        timestamp = datetime.fromisoformat(receipt['retired_at'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('retirement timestamp requires timezone')
        proof, proof_hash = _read(run, receipt['proof_path'])
        if (receipt['proof_path'] != 'runtime/execution_package/retirement_proofs/' + _digest(proof) + '.json'
                or proof_hash != receipt['proof_sha256'] or proof['run_id'] != run.name
                or proof['seal']['sha256'] != seal_hash or proof['eligible'] is not True):
            raise ValueError('retirement terminal proof changed')
        if any(summary.get(key) != value for key, value in proof['summary'].items()):
            raise ValueError('retired summary differs from terminal proof')
        return summary
    except (OSError, KeyError, TypeError) as error:
        raise ValueError('retired package history is missing or malformed') from error


def _collect_entry(run: Path, row: dict) -> int:
    """Input: owner Path and index-bound entry dict. Output: removed bytes; reject changed/link targets."""
    archived = read_archived_input(run, row['path'])
    path = _safe(run, row['path'])
    if not path.exists():
        return 0
    before = path.stat()
    raw = _bytes(run, row['path'], MAX_LOCAL_INPUT_BYTES)
    if raw != archived:
        raise ValueError('changed original package payload remains protected')
    after = _safe(run, row['path']).stat()
    if any(getattr(before, key) != getattr(after, key)
           for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_nlink')):
        raise ValueError('package payload changed before collection')
    path.unlink()
    return len(raw)


def _collect(run: Path) -> dict:
    """Input: committed retired owner Path. Output: idempotent exact-input collection receipt; never directory sweeps."""
    load_retired_summary(run)
    index = load_package_archive(run)
    removed_count = removed_bytes = 0
    # Verify every retained object before removing any remaining expanded input.
    for row in index['entries']:
        read_archived_input(run, row['path'])
    for row in index['entries']:
        existed = _safe(run, row['path']).exists()
        removed_bytes += _collect_entry(run, row)
        removed_count += int(existed)
    objects = {row['object_path']: row['gzip_bytes'] for row in index['entries']}
    total_bytes = sum(row['size'] for row in index['entries'])
    complete = dict(schema_version=1, run_id=run.name, status='retired',
        input_bytes=total_bytes, archive_object_bytes=sum(objects.values()),
        reclaimed_payload_bytes=total_bytes - sum(objects.values()),
        archive_sha256=_read(run, ARCHIVE_INDEX)[1])
    _store_immutable(run, COLLECTION_RECEIPT, complete)
    return dict(complete, removed_count=removed_count, removed_bytes=removed_bytes)


def _collection_fences(run: Path) -> ExitStack:
    """Input: owning run Path. Output: held intent/POST/group fences; reject Stop for first commit and replay alike."""
    from wqb.runtime_control import submission_request_gate, read_runtime_control, has_runtime_authority
    from wqb.research_group import group_for_run, _guard, read_group
    stack = ExitStack()
    try:
        stack.enter_context(json_lock_transition_guard(_safe(run, 'runtime/control_intent'),
            LOCK_SECONDS, LOCK_POLL_SECONDS, 'runtime intent busy during retirement'))
        stack.enter_context(submission_request_gate(run))
        group = group_for_run(run)
        if group is not None:
            directory = Path(group['group_dir'])
            stack.enter_context(_guard(directory))
            if read_group(directory)['desired_state'] != 'running':
                raise ValueError('group Stop prevents package collection')
        control = read_runtime_control(run)
        if (not has_runtime_authority(run) or control.get('invalid')
                or control.get('desired_state') != 'running'):
            raise ValueError('durable Stop or damaged intent prevents package collection')
        return stack
    except BaseException:
        stack.close()
        raise


def retire_execution_package(run: Path, now: str, *, worker_owner_id: str = '') -> dict:
    """Input: terminal owner/time and optional current driver lease token. Output: archival collection result.

    Scripts acquire or verify the existing worker lease. Compression happens
    before intent/POST fences; only the short commit and exact-file collection
    serialize with Stop. A committed retirement can recover after interruption.
    No scientific result, intent, budget, candidate cache or authority is changed.
    """
    from wqb.execution_retirement import terminal_retirement_proof
    from wqb.source_run_lock import acquire_source_run_lock, read_source_run_lock, release_source_run_lock
    from wqb.console_api import _lane

    run = _root(run)
    lock_root = _safe(run, 'runtime')
    acquired = None
    if worker_owner_id:
        lease = read_source_run_lock(lock_root)
        if (lease.get('status') != 'running' or lease.get('owner_id') != worker_owner_id
                or lease.get('pid') != os.getpid() or lease.get('action') != 'workflow-driver'):
            raise ValueError('package retirement requires the owning driver lease')
    else:
        acquired = acquire_source_run_lock(lock_root, 'package-retirement', now)
        if acquired.get('status') != 'acquired':
            raise ValueError('package retirement worker is busy or unknown')
    try:
        with json_lock_transition_guard(_safe(run, 'runtime/execution_package/retirement_guard'),
                LOCK_SECONDS, LOCK_POLL_SECONDS, 'package retirement busy'):
            if _safe(run, RETIRED_RECEIPT).exists():
                with _collection_fences(run):
                    return _collect(run)
            proof = terminal_retirement_proof(run)
            summary = dict(proof['summary'], console_projection=_lane(run))
            prepare_package_archive(run)
            with _collection_fences(run):
                if terminal_retirement_proof(run) != proof or _lane(run) != summary['console_projection']:
                    raise ValueError('terminal package evidence changed before retirement commit')
                summary_path = SUMMARY_ROOT + _digest(summary) + '.json'
                _store_immutable(run, summary_path, summary)
                proof_path = 'runtime/execution_package/retirement_proofs/' + _digest(proof) + '.json'
                _store_immutable(run, proof_path, proof)
                _, seal_hash = _owner_seal(run)
                timestamp = datetime.fromisoformat(now.replace('Z', '+00:00'))
                if timestamp.tzinfo is None:
                    raise ValueError('retirement timestamp requires timezone')
                receipt = dict(schema_version=1, kind='retired_execution_package', run_id=run.name,
                    retired_at=now, seal_sha256=seal_hash, summary_path=summary_path,
                    summary_sha256=_read(run, summary_path)[1],
                    archive_sha256=_read(run, ARCHIVE_INDEX)[1], proof_path=proof_path,
                    proof_sha256=_read(run, proof_path)[1])
                receipt['content_sha256'] = _digest(receipt)
                _store_immutable(run, RETIRED_RECEIPT, receipt)
                return _collect(run)
    finally:
        if acquired is not None and acquired.get('status') == 'acquired':
            release_source_run_lock(lock_root, 'package-retirement', now,
                                    owner_id=acquired['owner_id'])
