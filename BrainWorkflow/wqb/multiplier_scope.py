"""Official settings catalog and user-selected Multiplier scope, not activity eligibility."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from wqb.knowledge_age_policy import KNOWLEDGE_MAX_AGE_DAYS
from wqb.knowledge_contracts import SourceIndexRow, render_front_matter, parse_markdown_front_matter, upsert_source_index_rows
from wqb.lockfile import json_lock_transition_guard
from wqb.runtime_control import _write


CATALOG_PATH = 'machine/multiplier_scope_catalog.json'
MAX_SETTINGS_BYTES = 2 * 1024 * 1024
MAX_SCOPES = 4096
TOKEN_PATTERN = r'[A-Z][A-Z0-9_]*'


def multiplier_enabled(config: dict) -> bool:
    """Input: sanitized Start config. Output: new-only mode bool; never adopt the policy for frozen old runs."""
    policy = config.get('research_policy', {})
    value = policy.get('multiplier_scope_version', 0)
    if type(value) is not int or value not in (0, 1):
        raise ValueError('multiplier_scope_version must be integer 0 or 1')
    if value and policy.get('preplanned_tree_version') != 1:
        raise ValueError('manual Multiplier requires preplanned research')
    return value == 1


def _choice_values(field: dict, selectors: dict) -> list:
    """Input: OPTIONS field/selectors dicts. Output: explicit choice values; reject unknown dependency shapes."""
    value = field.get('choices')
    while isinstance(value, dict):
        dimension = next((key for key in ('instrumentType', 'region', 'delay') if key in value), None)
        if dimension is None or dimension not in selectors or not isinstance(value[dimension], dict):
            raise ValueError('unsupported platform settings choice dependency')
        mapping = value[dimension]
        selector = selectors[dimension]
        value = mapping.get(str(selector), mapping.get(selector, []))
    if not isinstance(value, list):
        raise ValueError('platform settings choices must be a list')
    return [item['value'] if isinstance(item, dict) and 'value' in item else item for item in value]


def _token(value) -> str:
    """Input: choice value. Output: exact uppercase platform token, or ValueError."""
    if not isinstance(value, str) or not re.fullmatch(TOKEN_PATTERN, value):
        raise ValueError('invalid platform scope token')
    return value


def compile_scope_choices(payload: dict, instrument_type: str = 'EQUITY') -> list[dict]:
    """Input: official OPTIONS payload/instrument string. Output: finite explicit region/delay/universe combinations."""
    try:
        settings = payload['actions']['POST']['settings']
        fields = settings.get('children', settings)
        result = set()
        for region in _choice_values(fields['region'], dict(instrumentType=instrument_type)):
            region = _token(region)
            selectors = dict(instrumentType=instrument_type, region=region)
            for delay in _choice_values(fields['delay'], selectors):
                if isinstance(delay, str) and re.fullmatch(r'0|[1-9]\d*', delay):
                    delay = int(delay)
                if type(delay) is not int or delay < 0:
                    raise ValueError('platform delay must be a nonnegative integer')
                for universe in _choice_values(fields['universe'], {**selectors, 'delay': delay}):
                    result.add((region, delay, _token(universe)))
                    if len(result) > MAX_SCOPES:
                        raise ValueError('platform scope catalog exceeds bound')
        if not result:
            raise ValueError('empty platform scope catalog')
        return [dict(region=region, delay=delay, universe=universe) for region, delay, universe in sorted(result)]
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid platform settings schema') from error


def _capture_time(value: str) -> datetime:
    """Input: recorded ISO timestamp. Output: aware datetime; never renew or accept future source dates."""
    if not isinstance(value, str):
        raise ValueError('settings capture date missing')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or (result - datetime.now(timezone.utc)).total_seconds() > 300:
        raise ValueError('invalid settings capture date')
    return result


def publish_scope_catalog(root: Path, payload: dict, captured_at: str) -> dict:
    """Input: vault Path, actual settings payload/date. Output: catalog receipt; preserve raw bytes/dates and index provenance."""
    from wqb.console_api import _safe
    root = Path(root).absolute()
    _capture_time(captured_at)
    choices = compile_scope_choices(payload)
    body = '# Official simulation settings\n\n```json\n' + json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n```\n'
    if len(body.encode()) > MAX_SETTINGS_BYTES:
        raise ValueError('settings source exceeds bound')
    digest = hashlib.sha256(body.encode()).hexdigest()
    identity = hashlib.sha256((captured_at + digest).encode()).hexdigest()
    relative = 'raw/platform/learn/' + captured_at[:10] + '/multiplier-scope-options-' + identity + '.md'
    source = _safe(root, root / relative)
    metadata = dict(source_type='platform_api', source_family='raw/platform/learn', source_path=relative,
        captured_at=captured_at, capture_tool='wqb.multiplier_scope', content_status='raw_markdown',
        record_count=len(choices), content_hash=digest, source_endpoint='OPTIONS /simulations',
        update_check='compare official OPTIONS settings and exact source hash', compiled_targets=[CATALOG_PATH])
    text = render_front_matter(metadata) + body
    with json_lock_transition_guard(root / 'machine/multiplier_scope_catalog_guard', 5.0, .02, 'scope catalog busy'):
        source.parent.mkdir(parents=True, exist_ok=True)
        try:
            with source.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(text)
        except FileExistsError:
            if source.read_text(encoding='utf-8') != text:
                raise ValueError('immutable settings capture changed')
        upsert_source_index_rows(root, [SourceIndexRow(path=relative, source_family='raw/platform/learn',
            source_type='platform_api', contents='Official available simulation region/delay/universe choices',
            update_check=metadata['update_check'], compiled_targets=[CATALOG_PATH], captured_at=captured_at,
            record_count=len(choices), content_hash=digest, content_status='raw_markdown')])
        receipt = dict(schema_version=1, source_path=relative, content_hash=digest, captured_at=captured_at, scopes=choices)
        _write(_safe(root, root / CATALOG_PATH), receipt)
    return receipt


def read_scope_catalog(root: Path) -> dict:
    """Input: vault Path. Output: source-recompiled settings choices with original age; no network or data-field admission gate."""
    from wqb.console_api import _read, _safe
    root = Path(root).absolute()
    receipt = _read(root, CATALOG_PATH)
    relative = receipt.get('source_path')
    if not isinstance(relative, str) or not re.fullmatch(r'raw/platform/learn/\d{4}-\d{2}-\d{2}/multiplier-scope-options-[0-9a-f]{64}\.md', relative):
        raise ValueError('invalid scope catalog source selector')
    source = _safe(root, root / relative)
    if source.stat().st_size > MAX_SETTINGS_BYTES + 8192:
        raise ValueError('scope source exceeds bound')
    metadata, body = parse_markdown_front_matter(source.read_text(encoding='utf-8'))
    digest = hashlib.sha256(body.encode()).hexdigest()
    captured = _capture_time(receipt.get('captured_at'))
    if (metadata.get('content_hash') != digest or receipt.get('content_hash') != digest
            or metadata.get('source_path') != relative or metadata.get('captured_at') != receipt['captured_at']
            or metadata.get('source_endpoint') != 'OPTIONS /simulations'):
        raise ValueError('settings provenance changed')
    prefix, suffix = '# Official simulation settings\n\n```json\n', '\n```\n'
    if not body.startswith(prefix) or not body.endswith(suffix):
        raise ValueError('invalid settings raw format')
    choices = compile_scope_choices(json.loads(body[len(prefix):-len(suffix)]))
    if receipt.get('schema_version') != 1 or receipt.get('scopes') != choices:
        raise ValueError('compiled settings differ from official raw')
    return {**receipt, 'stale': (datetime.now(timezone.utc) - captured).total_seconds() > KNOWLEDGE_MAX_AGE_DAYS * 86400}


def select_multiplier_scope(catalog: dict, config: dict, selection: dict) -> dict:
    """Input: catalog/config/user selection dicts. Output: one exact allowed scope; saved universe only within selected region."""
    if (not isinstance(selection, dict) or set(selection) - {'region', 'delay', 'universe'}
            or type(selection.get('delay')) is not int or selection['delay'] < 0):
        raise ValueError('select a region and integer delay')
    region, delay = _token(selection.get('region')), selection['delay']
    universes = {item['universe'] for item in catalog['scopes'] if item['region'] == region and item['delay'] == delay}
    if not universes:
        raise ValueError('region and delay are not supported by platform settings')
    universe = selection.get('universe')
    if universe is None:
        saved = config.get('selected_scope', config)
        universe = saved.get('universe') if isinstance(saved, dict) and saved.get('region') == region else None
    if universe not in universes:
        raise ValueError('select a valid universe for this region and delay')
    return dict(region=region, delay=delay, universe=universe)


def scope_selection_contract(root: Path, config: dict) -> dict:
    """Input: vault Path/saved config. Output: local-only dropdown contract, independent of local field coverage."""
    catalog = read_scope_catalog(root)
    saved = config.get('selected_scope', config)
    configured = {key: saved.get(key) for key in ('region', 'delay', 'universe')} if isinstance(saved, dict) else None
    if configured is not None and (type(configured['delay']) is not int or configured['delay'] < 0
            or any(not isinstance(configured[key], str) or not configured[key] for key in ('region', 'universe'))):
        configured = None
    return dict(choices=catalog['scopes'], configured_scope=configured,
                captured_at=catalog['captured_at'], stale=catalog['stale'])
