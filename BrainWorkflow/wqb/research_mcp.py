"""Task-bound MCP stdio adapter for the existing quota-accounted local query service."""
import json
import os
from pathlib import Path
import sys

from wqb.research_tool_service import MAX_ARGUMENT_BYTES, OPERATIONS


MAX_MESSAGE_BYTES = MAX_ARGUMENT_BYTES + 8192
MCP_STARTUP_SECONDS = 20
MCP_TOOL_SECONDS = 35
QUERY_TOOL = dict(name='query', description='Read exact-scope local knowledge or validate a complete draft. '
    'FIRST call operation=contract with arguments_json={"section":"overview"}; then read '
    'composition_contract, tool_contracts and output_schema sections (follow next_start). '
    'Discover local raw/machine/wiki paths with resources; source reads paged text with {"path":"relative path"}, '
    'NOT source_path or website URLs. Missing optional knowledge is feedback, not a command to stop. '
    'Use validate diagnostics to correct drafts before final output. No platform calls.',
    inputSchema=dict(type='object', properties=dict(
        operation=dict(type='string', enum=sorted(OPERATIONS)),
        arguments_json=dict(type='string', maxLength=MAX_ARGUMENT_BYTES, description='JSON object using task.tool_contracts.')),
        required=['operation', 'arguments_json'], additionalProperties=False),
    annotations=dict(readOnlyHint=True, destructiveHint=False, openWorldHint=False))


def codex_config(directory: Path) -> dict:
    """Input: owning task Path. Output: per-process Codex MCP config; no persistent config or permission changes."""
    if getattr(sys, 'frozen', False):
        args = ['--worker-module', 'wqb.retrieval_research_planning']
    else:
        args = ['-B', str(Path(__file__).resolve().parents[1] / 'scripts/research_query.py')]
    return dict(command=sys.executable, args=args + ['mcp', '--task-dir', str(Path(directory).absolute())],
        required=True, enabled_tools=['query'], default_tools_approval_mode='auto', startup_timeout_sec=MCP_STARTUP_SECONDS,
        tool_timeout_sec=MCP_TOOL_SECONDS)


def stdin_stream():
    """Input: inherited process handles. Output: binary stdin stream, including a windowed Windows executable."""
    if sys.stdin is not None:
        return sys.stdin.buffer
    if os.name != 'nt':
        raise RuntimeError('MCP requires inherited stdin')
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    handle = kernel.GetStdHandle(0xFFFFFFF6)
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise RuntimeError('MCP requires inherited stdin pipe')
    return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), 'rb')


def serve(directory: Path, stream=None, emit=None) -> int:
    """Input: fixed task Path/optional binary stream and emitter. Output: exit code; JSON-RPC only, no authority expansion."""
    from wqb.retrieval_research_planning import authenticated_design_task, emit_query_result
    from wqb.research_tool_service import request_tool
    stream = stdin_stream() if stream is None else stream
    emit = emit_query_result if emit is None else emit
    initialized = False
    while True:
        raw = stream.readline(MAX_MESSAGE_BYTES + 1)
        if not raw:
            return 0
        if len(raw) > MAX_MESSAGE_BYTES:
            return 2
        request = {}
        try:
            request = json.loads(raw)
            if not isinstance(request, dict) or request.get('jsonrpc') != '2.0':
                raise ValueError('invalid MCP request')
            if 'id' not in request:
                continue
            method, params = request.get('method'), request.get('params', {})
            if method == 'initialize':
                authenticated_design_task(directory)
                initialized = True
                result = dict(protocolVersion=params['protocolVersion'], capabilities=dict(tools={}),
                    serverInfo=dict(name='brain-research', version='1.0'))
            elif not initialized:
                raise ValueError('MCP initialize required')
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = dict(tools=[QUERY_TOOL])
            elif method == 'tools/call':
                try:
                    if params.get('name') != 'query':
                        raise ValueError('unknown task tool')
                    args = params['arguments']
                    if set(args) != {'operation', 'arguments_json'} or args['operation'] not in OPERATIONS:
                        raise ValueError('invalid task query arguments')
                    arguments = json.loads(args['arguments_json'])
                    value = request_tool(directory, args['operation'], arguments)
                    result = dict(content=[dict(type='text', text=json.dumps(value, ensure_ascii=False))], isError=False)
                except (OSError, ValueError, TypeError, KeyError, InterruptedError) as error:
                    result = dict(content=[dict(type='text', text=str(error)[:1000])], isError=True)
            else:
                raise ValueError('unsupported MCP method')
            emit(dict(jsonrpc='2.0', id=request['id'], result=result))
        except (OSError, ValueError, TypeError, KeyError, InterruptedError) as error:
            emit(dict(jsonrpc='2.0', id=request.get('id') if isinstance(request, dict) else None,
                error=dict(code=-32600, message=str(error)[:1000])))
