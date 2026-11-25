"""Task-local read-only tool transport with owner-side budgets and display progress."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from multiprocessing.connection import Client, Listener
from multiprocessing import AuthenticationError
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from wqb.runtime_control import _write
from wqb.semantic_compilation import _safe


BROKER_PATH = 'runtime/retrieval_research_planning/broker.json'
PROGRESS_PATH = 'runtime/retrieval_research_planning/progress.json'
MAX_ARGUMENT_BYTES = 64_000
MAX_RESPONSE_BYTES = 64_000
DEFAULT_MAX_QUERIES = 64
DEFAULT_MAX_VALIDATIONS = 24
DEFAULT_MAX_RETURNED_BYTES = 1_048_576
CLIENT_WAIT_SECONDS = 30
OPERATIONS = {'contract', 'fields', 'operators', 'templates', 'experience', 'source', 'resources', 'validate'}


def _bytes(value: object) -> bytes:
    """Input: JSON value. Output: strict UTF-8 bytes; never pickle untrusted tool requests."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def tool_limits(config: dict) -> dict:
    """Input: nonsecret task config. Output: exact positive local-tool budgets, independent of simulations."""
    limits = dict(max_queries=config.get('retrieval_max_queries', DEFAULT_MAX_QUERIES),
        max_validations=config.get('retrieval_max_validations', DEFAULT_MAX_VALIDATIONS),
        max_returned_bytes=config.get('retrieval_max_returned_bytes', DEFAULT_MAX_RETURNED_BYTES))
    if any(type(value) is not int or value <= 0 for value in limits.values()):
        raise ValueError('retrieval tool budgets require positive integers')
    return limits


class ToolBudget:
    """Account only the allowed tool interface; it is not a sandbox filesystem allowlist."""

    def __init__(self, limits: dict):
        """Input: validated limit dict. Output: task-owned zero-use counter, not research or model-call authority."""
        self.limits, self.queries, self.validations, self.returned_bytes = limits, 0, 0, 0
        self.rows_returned, self.source_bytes, self.elapsed_seconds = 0, 0, 0.0

    def execute(self, operation: str, arguments: dict, evaluator) -> dict:
        """Input: allowed operation/JSON args/callable. Output: bounded result with exact cumulative counters."""
        if operation not in OPERATIONS or not isinstance(arguments, dict):
            raise ValueError('unsupported local tool request')
        if len(_bytes(arguments)) > MAX_ARGUMENT_BYTES:
            raise ValueError('tool arguments exceed byte bound')
        if self.queries >= self.limits['max_queries']:
            raise ValueError('retrieval_query_budget_exhausted')
        if operation == 'validate' and self.validations >= self.limits['max_validations']:
            raise ValueError('retrieval_validation_budget_exhausted')
        self.queries += 1
        self.validations += int(operation == 'validate')
        started = time.monotonic()
        try:
            result = evaluator(operation, arguments)
        finally:
            self.elapsed_seconds = round(self.elapsed_seconds + time.monotonic() - started, 6)
        items = result.get('items', [])
        rows = len(items)
        source_bytes = sum(len(item.get('excerpt', '').encode('utf-8')) for item in items)
        total = self.returned_bytes
        for _ in range(8):
            reply = dict(result, tool_budget={**self.snapshot(), 'returned_bytes': total,
                'rows_returned': self.rows_returned + rows, 'source_bytes': self.source_bytes + source_bytes})
            measured = self.returned_bytes + len(_bytes(reply))
            if measured == total:
                break
            total = measured
        if len(_bytes(reply)) > MAX_RESPONSE_BYTES:
            raise ValueError('local tool response exceeds byte bound; request fewer fields')
        if total > self.limits['max_returned_bytes']:
            raise ValueError('retrieval_response_budget_exhausted')
        self.returned_bytes = total
        self.rows_returned += rows
        self.source_bytes += source_bytes
        return reply

    def snapshot(self) -> dict:
        """Input: self. Output: copied counts/limits; no raw queries, credentials or inferred research progress."""
        return dict(queries=self.queries, validations=self.validations,
                    returned_bytes=self.returned_bytes, rows_returned=self.rows_returned,
                    source_bytes=self.source_bytes, elapsed_seconds=self.elapsed_seconds, **self.limits)


@contextmanager
def local_tool_service(directory: Path, task: dict):
    """Input: running task Path/state. Output: owner-only local service lifetime; no platform/model actions."""
    config = task['identity']['config']
    budget = ToolBudget(tool_limits(config))
    token = task['input_sha256']
    family = 'AF_PIPE' if os.name == 'nt' else 'AF_INET'
    address = r'\\.\pipe\brain-research-' + uuid4().hex if os.name == 'nt' else ('127.0.0.1', 0)
    authkey = os.urandom(32)
    listener = Listener(address=address, family=family, authkey=authkey)
    local_address = listener.address
    descriptor = dict(schema_version=1, input_sha256=token, family=family,
                      address=local_address, authkey=authkey.hex())
    _write(_safe(directory, BROKER_PATH), descriptor)

    def serve():
        """Input: none. Output: none; serialize tool access and sanitize all telemetry at its owner."""
        from wqb.retrieval_research_planning import _query_design_task_local
        while True:
            try:
                connection = listener.accept()
            except AuthenticationError:
                continue
            except (OSError, EOFError):
                break
            with connection:
                request = {}
                try:
                    if not connection.poll(CLIENT_WAIT_SECONDS):
                        continue
                    decoded = json.loads(connection.recv_bytes(MAX_ARGUMENT_BYTES + 4096))
                    if not isinstance(decoded, dict):
                        raise ValueError('invalid local tool envelope')
                    request = decoded
                    if request.get('input_sha256') != token:
                        raise ValueError('local tool task identity mismatch')
                    if request.get('close') is True:
                        connection.send_bytes(_bytes({'closed': True}))
                        break
                    if set(request) != {'input_sha256', 'operation', 'arguments'}:
                        raise ValueError('invalid local tool envelope')
                    operation = request['operation'] if isinstance(request['operation'], str) else ''
                    progress = dict(input_sha256=token, stage='validating' if operation == 'validate' else 'retrieving',
                        operation=operation if operation in OPERATIONS else '',
                        activity_at=datetime.now(timezone.utc).isoformat(), **budget.snapshot())
                    _write(_safe(directory, PROGRESS_PATH), progress)
                    result = budget.execute(operation, request['arguments'],
                        lambda op, args: _query_design_task_local(directory, op, args))
                    response = dict(result=result)
                except Exception as error:
                    response = dict(error=type(error).__name__, message=str(error)[:1000])
                try:
                    progress = dict(input_sha256=token, stage='planning',
                        operation=(request['operation'] if isinstance(request.get('operation'), str)
                                   and request['operation'] in OPERATIONS else ''),
                        activity_at=datetime.now(timezone.utc).isoformat(), **budget.snapshot())
                    _write(_safe(directory, PROGRESS_PATH), progress)
                    connection.send_bytes(_bytes(response))
                except (OSError, EOFError, ValueError):
                    pass
        listener.close()

    thread = threading.Thread(target=serve, name='research-readonly-tools', daemon=True)
    thread.start()
    try:
        yield budget
    finally:
        try:
            if thread.is_alive():
                with Client(local_address, family=family, authkey=authkey) as connection:
                    connection.send_bytes(_bytes(dict(input_sha256=token, close=True)))
                    if connection.poll(CLIENT_WAIT_SECONDS):
                        connection.recv_bytes(4096)
        finally:
            thread.join(timeout=CLIENT_WAIT_SECONDS)
            listener.close()
        if thread.is_alive():
            raise RuntimeError('local research tool service did not stop')


def request_tool(directory: Path, operation: str, arguments: dict) -> dict:
    """Input: task Path/op/args. Output: local owner response; client never writes task or knowledge files."""
    from wqb.retrieval_research_planning import read_design_task
    task = read_design_task(directory)
    if task['status'] != 'running':
        raise ValueError('query requires the owning running design task')
    descriptor = json.loads(_safe(directory, BROKER_PATH).read_text(encoding='utf-8'))
    if descriptor.get('input_sha256') != task['input_sha256'] or descriptor.get('family') not in {'AF_PIPE', 'AF_INET'}:
        raise ValueError('invalid local research tool descriptor')
    address = descriptor['address']
    if descriptor['family'] == 'AF_INET':
        address = tuple(address)
        if address[0] != '127.0.0.1':
            raise ValueError('research tool transport must be local')
    elif not isinstance(address, str) or not address.startswith(r'\\.\pipe\brain-research-'):
        raise ValueError('research tool transport must be task-local')
    request = _bytes(dict(input_sha256=task['input_sha256'], operation=operation, arguments=arguments))
    if len(request) > MAX_ARGUMENT_BYTES + 4096:
        raise ValueError('local tool envelope exceeds byte bound')
    with Client(address, family=descriptor['family'], authkey=bytes.fromhex(descriptor['authkey'])) as connection:
        connection.send_bytes(request)
        if not connection.poll(CLIENT_WAIT_SECONDS):
            raise TimeoutError('local research tool response timed out')
        response = json.loads(connection.recv_bytes(MAX_RESPONSE_BYTES + 4096))
    if 'error' in response:
        raise ValueError(response['message'])
    return response['result']
