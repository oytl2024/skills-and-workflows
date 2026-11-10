"""Readonly explanation transport; strict wire encoding grants no factual authority."""
from copy import deepcopy
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import time

from wqb.full_semantic_compile import _json
from wqb.semantic_compilation import _check_schema


MODEL_GUARD_SECONDS = 1.0
MODEL_GUARD_POLL_SECONDS = 0.02


def strict_worker_schema(schema: dict) -> dict:
    """Input: canonical JSON schema dict. Output: closed model schema; arbitrary values become JSON strings."""
    if schema == {}:
        return dict(type='string', description='One JSON-encoded source value; no prose or formulas.')
    if 'anyOf' in schema:
        return dict(anyOf=[strict_worker_schema(branch) for branch in schema['anyOf']])
    result = deepcopy(schema)
    if schema.get('type') == 'object':
        if schema.get('additionalProperties') is not False:
            raise ValueError('model objects require an explicit closed property contract')
        required = set(schema.get('required', []))
        result['properties'] = {}
        for key, value in schema['properties'].items():
            converted = strict_worker_schema(value)
            result['properties'][key] = converted if key in required else dict(
                anyOf=[converted, dict(type='null')])
        result['required'] = list(schema['properties'])
    elif schema.get('type') == 'array':
        result['items'] = strict_worker_schema(schema['items'])
    return result


def normalize_worker_answer(schema: dict, answer):
    """Input: canonical schema dict/model value. Output: canonical JSON value after strict syntax validation."""
    _check_schema(strict_worker_schema(schema), answer)
    if schema == {}:
        return _json(answer)
    if 'anyOf' in schema:
        for branch in schema['anyOf']:
            try:
                _check_schema(strict_worker_schema(branch), answer)
            except ValueError:
                continue
            return normalize_worker_answer(branch, answer)
        raise ValueError('no matching explanation wire branch')
    if schema.get('type') == 'object':
        required = set(schema.get('required', []))
        normalized = {key: normalize_worker_answer(value, answer[key])
            for key, value in schema['properties'].items()
            if key in required or answer[key] is not None}
    elif schema.get('type') == 'array':
        normalized = [normalize_worker_answer(schema['items'], value) for value in answer]
    else:
        normalized = answer
    return normalized


def create_full_semantic_model_runner(root: Path, plan: dict, config: dict):
    """Input: vault Path/authenticated-plan candidate/config dict. Output: bounded readonly executor callback.

    The execution owner authenticates budget before invoking this callback. This
    adapter authenticates job evidence and cannot grant publication or retries.
    """
    from wqb import ai_checkpoints
    from wqb.full_semantic_execution import (load_bound_explanation_job,
        full_semantic_output_schema, validate_full_semantic_output, require_full_semantic_reservation)
    from wqb.lockfile import json_lock_transition_guard
    from wqb.semantic_compilation import _safe
    from wqb.workflow_driver import resolve_ai_executor_argv
    root = Path(root).absolute()
    if any(path.is_symlink() or path.is_junction() for path in (root, *root.parents)):
        raise ValueError('linked explanation root denied')
    root = root.resolve(strict=True)
    if config.get('ai_executor', 'codex') != 'codex':
        raise ValueError('full semantic explanations require the readonly Codex executor')
    key = plan.get('content_key')
    if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}', key):
        raise ValueError('invalid explanation plan identity')
    plan_control = _safe(root, f'machine/semantic_jobs/{key}/control.json')
    argv = resolve_ai_executor_argv(dict(ai_executor='codex'))

    def runner(*, job: dict, output_schema: dict, deadline: float) -> dict:
        """Input: verified job/schema/absolute epoch deadline. Output: complete validated answer, one model attempt."""
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= time.time():
            raise ValueError('explanation deadline exhausted or invalid')
        current = load_bound_explanation_job(Path(job['job_dir']))
        if current != job or Path(current['root']) != root or full_semantic_output_schema(current) != output_schema:
            raise ValueError('explanation callback differs from authenticated job or schema')
        authority = require_full_semantic_reservation(current)
        if authority['owner_plan'] != key or authority['deadline'] != deadline:
            raise ValueError('explanation deadline or owning reservation differs from plan')
        job_control = _safe(root, Path(current['job_dir']).relative_to(root).as_posix() + '/control.json')

        def cancelled() -> bool:
            """Input: none. Output: bool; preserve plan/job cancellation and original absolute deadline."""
            if time.time() >= deadline:
                return True
            for control in (plan_control, job_control):
                if control.exists():
                    value = _json(control.read_text(encoding='utf-8'))
                    if not isinstance(value, dict) or value.get('cancelled') is True:
                        return True
            return False

        if cancelled():
            raise RuntimeError('full semantic explanation cancelled')
        directory = Path(current['job_dir']) / 'stages/ai'
        directory.mkdir(parents=True, exist_ok=True)
        with json_lock_transition_guard(directory / 'explanation_model_guard', MODEL_GUARD_SECONDS,
                                        MODEL_GUARD_POLL_SECONDS, 'explanation model busy'):
            if ai_checkpoints.load_ai_checkpoints(directory):
                raise ValueError('explanation checkpoint already exists; no replay')
            checkpoint = ai_checkpoints.append_ai_checkpoint(directory, 'full_semantic_explanation',
                'Explain the complete frozen local target batch without granting factual trust.', ['input.json'],
                datetime.now(timezone.utc).isoformat())
        timeout = max(1, min(ai_checkpoints.DEFAULT_EXECUTOR_TIMEOUT_SECONDS, int(deadline - time.time())))
        result = ai_checkpoints.run_ai_checkpoint(directory, checkpoint.checkpoint_id, argv,
            timeout_seconds=timeout, cancel_on_pause=False, cancellation_check=cancelled)
        if result.get('status') != 'completed' or cancelled():
            raise RuntimeError('full semantic checkpoint incomplete or cancelled: ' + str(result.get('status')))
        if load_bound_explanation_job(Path(current['job_dir'])) != current:
            raise ValueError('explanation evidence changed during execution')
        answer = {key: deepcopy(result[key]) for key in ('summary', 'targets')}
        validate_full_semantic_output(root, current, answer)
        return answer

    return runner
