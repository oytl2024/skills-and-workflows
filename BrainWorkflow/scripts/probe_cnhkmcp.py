"""Bounded maintenance-only CNHK MCP probe. No research model, simulations or credential files."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
import zipfile


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
WHEEL_SHA256 = 'e2f4473bede44dc1db98223ba669144fd88a057005dbc6642213e0970a756a57'
UPSTREAM_PATH = 'cnhkmcp/untracked/platform_functions.py'
MAX_READS = 8
MAX_SECONDS = 120
REQUEST_SECONDS = 12
DOC_IDS = ('introduction-brain-expression-language', 'vector-datafields')


class ReadOnlySession:
    def __init__(self, client, max_reads: int = MAX_READS):
        """Input: existing authenticated client/int cap. Output: read-only adapter with bounded allowed metadata routes."""
        self.client, self.max_reads, self.reads = client, max_reads, 0
        self.started = time.monotonic()

    def request(self, method: str, url: str, **kwargs):
        """Input: method/URL/kwargs. Output: bounded response; never forward writes,foreign hosts,queries or redirects."""
        from wqb.client import BASE_URL
        parsed, base = urlsplit(url), urlsplit(BASE_URL)
        valid = ((method == 'GET' and parsed.path in {'/operators', '/tutorials'}) or
                 (method == 'GET' and re.fullmatch(r'/tutorial-pages/[A-Za-z0-9_-]+', parsed.path)) or
                 (method == 'OPTIONS' and parsed.path == '/simulations'))
        if ((parsed.scheme, parsed.netloc) != (base.scheme, base.netloc) or parsed.query or parsed.fragment or
                not valid or kwargs):
            raise ValueError('CNHK probe permits metadata reads only')
        if self.reads >= self.max_reads or time.monotonic() - self.started >= MAX_SECONDS:
            raise ValueError('CNHK probe read budget exhausted')
        self.reads += 1
        return self.client.request(method, parsed.path, respect_retry_after=False, allow_redirects=False)

    def get(self, url: str, **kwargs):
        """Input: metadata URL/kwargs. Output: GET response within read budget."""
        return self.request('GET', url, **kwargs)

    def options(self, url: str, **kwargs):
        """Input: settings URL/kwargs. Output: OPTIONS response;never POST a simulation."""
        return self.request('OPTIONS', url, **kwargs)


def load_upstream(wheel: Path, destination: Path):
    """Input: verified wheel/destination Paths. Output: inspected upstream module;avoid broken package exports/main."""
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != WHEEL_SHA256:
        raise ValueError('CNHK distribution hash differs from inspected release')
    with zipfile.ZipFile(wheel) as archive:
        extracted = Path(archive.extract(UPSTREAM_PATH, destination))
    spec = importlib.util.spec_from_file_location('brain_cnhk_probe_upstream', extracted)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def bootstrap_sdk(root: Path):
    """Input: isolated SDK Path. Output: DLL handle or None;no global installation or persistent configuration."""
    for relative in ('', 'win32', 'win32/lib'):
        sys.path.insert(0, str(root / relative))
    sys.path.insert(0, str(PRODUCT_ROOT))
    if os.name == 'nt':
        return os.add_dll_directory(str((root / 'pywin32_system32').resolve()))
    return None


def serve(args) -> None:
    """Input: verified probe args. Output: stdio MCP server with3 read tools;credentials remain in existing session memory."""
    from mcp.server.fastmcp import FastMCP
    from wqb.client import WQBClient
    upstream = load_upstream(args.wheel, args.wheel.parent / 'source')
    client = WQBClient(timeout_seconds=REQUEST_SECONDS, max_retries=0)
    client.authenticate()
    upstream.brain_client.session = ReadOnlySession(client)

    async def authenticated():
        """Input: none. Output: None;reuse positively authenticated existing client without upstream credential persistence."""
        if not client.authenticated:
            raise ValueError('Existing platform session is not authenticated')

    upstream.brain_client.ensure_authenticated = authenticated
    server = FastMCP('brain-cnhk-readonly-probe')
    for name in ('get_operators', 'get_documentation_page', 'get_platform_setting_options'):
        server.add_tool(getattr(upstream, name), name=name)
    server.run()


def summarize(name: str, data: dict) -> dict:
    """Input: tool name/decoded response. Output: compact public metadata evidence,not a full saved platform inventory."""
    result = dict(tool=name, sha256=hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest())
    if name == 'get_operators':
        rows = data.get('operators', data.get('results', []))
        result['count'] = len(rows)
        result['selected'] = [{key: row.get(key) for key in ('name', 'definition', 'description', 'scopes')}
            for row in rows if row.get('name') in {'and', 'or', 'not', 'add', 'if_else', 'ts_decay_linear'}]
    elif name == 'get_platform_setting_options':
        result['scope_groups'] = data.get('total_combinations')
    else:
        result.update(id=data.get('id'), title=data.get('title'), lastModified=data.get('lastModified'),
                      content_blocks=len(data.get('content', [])))
    return result


async def probe(args) -> list[dict]:
    """Input: explicit live args. Output:4 bounded real MCP tool results;no simulated/model requests."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from datetime import timedelta
    params = StdioServerParameters(command=sys.executable,
        args=[str(Path(__file__).resolve()), '--live', '--serve', '--wheel', str(args.wheel),
              '--sdk-root', str(args.sdk_root)], env=dict(os.environ, PYTHONUTF8='1'))
    results = []
    with open(os.devnull, 'w') as quiet:
        async with stdio_client(params, errlog=quiet) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=MAX_SECONDS)) as session:
                await session.initialize()
                listed = await session.list_tools()
                allowed = sorted(tool.name for tool in listed.tools)
                if allowed != ['get_documentation_page', 'get_operators', 'get_platform_setting_options']:
                    raise ValueError('Unexpected CNHK probe tool exposure')
                for name, arguments in [('get_operators', {}), ('get_platform_setting_options', {})] + [
                        ('get_documentation_page', dict(page_id=identity)) for identity in DOC_IDS]:
                    reply = await session.call_tool(name, arguments)
                    if reply.isError:
                        results.append(dict(tool=name, status='failed', reason='MCP tool returned an error'))
                        continue
                    payload = json.loads(next(item.text for item in reply.content if item.type == 'text'))
                    if payload.get('error'):
                        results.append(dict(tool=name, status='failed', reason='Upstream tool returned an error'))
                        continue
                    results.append(summarize(name, payload))
    return results


def main() -> int:
    """Input: CLI args. Output: exit code;live network requires explicit flag and workspace-contained SDK/wheel/output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--sdk-root', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    for path in (args.wheel, args.sdk_root, args.output):
        if path is not None and not path.resolve().is_relative_to((PRODUCT_ROOT / 'output').resolve()):
            parser.error('Probe paths must stay within product output')
    args.wheel, args.sdk_root = args.wheel.resolve(), args.sdk_root.resolve()
    if not args.live:
        parser.error('Use --live only for explicitly authorized read-only platform investigation')
    dll_handle = bootstrap_sdk(args.sdk_root)
    if args.serve:
        serve(args)
    else:
        from datetime import datetime, timezone
        value = dict(captured_at=datetime.now(timezone.utc).isoformat(), version='cnhkmcp4.3.17',
                     wheel_sha256=WHEEL_SHA256, results=asyncio.run(probe(args)))
        text = json.dumps(value, ensure_ascii=True, indent=2)
        if args.output:
            args.output.write_text(text + '\n', encoding='utf-8')
        print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
