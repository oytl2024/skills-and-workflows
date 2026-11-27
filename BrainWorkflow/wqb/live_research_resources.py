"""CNHK-compatible resource reads using the existing authenticated WQB transport.

This is an adapter, not execution of the third-party package. Responses are data,
not instructions; only the owning task's exact scope can be queried.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlencode


DEFAULT_MAX_REQUESTS = 24
MAX_PAGE_SIZE = 50
MAX_PAYLOAD_BYTES = 512_000
RESOURCE_TOOLS = ('get_datafields', 'get_datasets', 'get_operators',
                  'get_documentations', 'get_documentation_page', 'get_platform_setting_options')


def live_mode(config: dict) -> bool:
    """Input: config or frozen policy dict. Output: bool for the explicit new live-MCP contract."""
    value = config.get('live_mcp_version', config.get('research_policy', {}).get('live_mcp_version', 0))
    if type(value) is not int or value not in (0, 1):
        raise ValueError('live_mcp_version must be integer 0 or 1')
    return value == 1


def _text(value) -> str:
    """Input: JSON value. Output: stable UTF-8-compatible text without interpreting content."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


def selected_resources(responses: list, selection: list, scope: dict, settings: dict,
                       *, operators: set | None = None) -> dict:
    """Input: task-returned response dicts, selected pairs/scope/settings. Output: minimal compiler resources."""
    fields, known_operators = {}, {}
    for response in responses:
        payload, source = response['payload'], response['source']
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        if (response['scope'] != scope or hashlib.sha256(raw).hexdigest() != source['sha256']
                or source.get('method') not in ('GET', 'OPTIONS')):
            raise ValueError('task resource response integrity or scope changed')
        if response['tool'] == 'get_datafields':
            from wqb.data_catalog import _payload_rows_and_count
            for row in _payload_rows_and_count(payload)[0]:
                dataset = row.get('dataset', {})
                if isinstance(dataset, dict) and isinstance(dataset.get('id'), str) and isinstance(row.get('id'), str):
                    key = (dataset['id'], row['id'])
                    if key in fields and fields[key][0] != row:
                        raise ValueError('conflicting task field observations')
                    fields[key] = (row, source)
        elif response['tool'] == 'get_operators':
            rows = payload if isinstance(payload, list) else payload.get('results', payload.get('operators', []))
            for row in rows:
                name = row.get('name', row.get('operator'))
                if isinstance(name, str):
                    if name in known_operators and known_operators[name][0] != row:
                        raise ValueError('conflicting task operator observations')
                    known_operators[name] = (row, source)
    index, texts, field_rows, operator_rows = {}, {}, [], []

    def material(kind, fact, source):
        """Input: fact kind/string, returned dict and provenance. Output: task-local material path str."""
        text = _text(dict(kind=kind, fact=fact, scope=scope, origin=source))
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        path = 'live/' + kind + '/' + digest + '.json'
        index[path] = dict(path=path, content_hash=digest, captured_at=source['captured_at'],
                           source_url=source['path'], origin_sha256=source['sha256'])
        texts[path] = text
        return path

    for dataset, field in sorted(set(selection)):
        if (dataset, field) not in fields:
            raise ValueError('field was not returned for this task scope: ' + dataset + '/' + field)
        fact, source = fields[(dataset, field)]
        path = material('field', fact, source)
        row = dict(scope, dataset_id=dataset, field_id=field, field_type=fact.get('type', 'UNKNOWN'),
                   source_paths=[path], field_description=fact.get('description', ''),
                   source_updated_at=source['captured_at'][:10])
        field_rows.append(row)
    for name, (fact, source) in sorted(known_operators.items()):
        if operators is not None and name not in operators:
            continue
        path = material('operator', fact, source)
        row = dict(operator=name, source_paths=[path], raw_description=fact.get('description', ''))
        if isinstance(fact.get('definition'), str):
            row['raw_definition'] = fact['definition']
        operator_rows.append(row)
    pack = dict(resource_contract_version=2, scope=deepcopy(scope), source_index=index,
                source_texts=texts, histories=[], allowed_role_semantics=[], allowed_operator_intents=[])
    return dict(live_mcp_version=1, expression_tool_version=1, technical_exploration_version=1,
                direct_knowledge_version=1, resource_contract_version=2, field_rows=field_rows,
                operator_rows=operator_rows, settings=deepcopy(settings), source_index=index,
                source_texts=texts, evidence_pack=pack)


def verify_resources(resources: dict, scope: dict) -> None:
    """Input: script-selected resources/scope. Output: None; verify frozen source identity, not semantic confidence."""
    if not live_mode(resources) or resources['evidence_pack']['scope'] != scope:
        raise ValueError('live resource scope or contract mismatch')
    index, texts = resources['source_index'], resources['source_texts']
    if set(index) != set(texts):
        raise ValueError('live resource material set changed')
    for path, source in index.items():
        if source['path'] != path or hashlib.sha256(texts[path].encode('utf-8')).hexdigest() != source['content_hash']:
            raise ValueError('live resource bytes changed')
        material = json.loads(texts[path])
        origin = material['origin']
        if (material['scope'] != scope or source['captured_at'] != origin['captured_at']
                or source['source_url'] != origin['path'] or source['origin_sha256'] != origin['sha256']
                or path != 'live/'+material['kind']+'/'+source['content_hash']+'.json'):
            raise ValueError('live resource provenance changed')
    if resources['evidence_pack']['source_index'] != index or resources['evidence_pack']['source_texts'] != texts:
        raise ValueError('live resource evidence differs')
    for row in resources['field_rows']:
        if any(row.get(key) != value for key, value in scope.items()):
            raise ValueError('live field scope mismatch')
        for path in row['source_paths']:
            observed = json.loads(texts[path])
            fact = observed['fact']
            if (observed['kind'] != 'field' or observed['scope'] != scope
                    or (fact.get('dataset', {}).get('id'), fact.get('id'), fact.get('type', 'UNKNOWN')) !=
                    (row['dataset_id'], row['field_id'], row['field_type'])):
                raise ValueError('live field identity or type changed')
            if row.get('field_description','') != fact.get('description',''):
                raise ValueError('live field description changed')
    for row in resources['operator_rows']:
        for path in row['source_paths']:
            observed = json.loads(texts[path])
            fact = observed['fact']
            if (observed['kind'] != 'operator' or row['operator'] != fact.get('name',fact.get('operator'))
                    or row.get('raw_definition','') != (fact.get('definition','') if isinstance(fact.get('definition',''),str) else '')
                    or row.get('raw_description','') != fact.get('description','') or 'definition' in row):
                raise ValueError('live operator facts changed or unproven typed contract added')


class LiveResearchResources:
    def __init__(self, client, scope: dict, *, max_requests: int = DEFAULT_MAX_REQUESTS,
                 check_cancelled=lambda: None):
        """Input: WQB client, exact scope dict, int cap and callback. Output: task-owned read cache."""
        if type(max_requests) is not int or max_requests <= 0:
            raise ValueError('resource request budget must be a positive integer')
        if (not {'instrument_type', 'region', 'delay', 'universe'} <= set(scope)
                or set(scope) - {'instrument_type', 'region', 'delay', 'universe', 'as_of'}
                or type(scope['delay']) is not int or scope['delay'] < 0
                or any(not isinstance(scope[key], str) or not scope[key].strip()
                       for key in ('instrument_type', 'region', 'universe'))):
            raise ValueError('resources require one exact scope')
        self.client, self.scope = client, deepcopy(scope)
        self.max_requests, self.check_cancelled = max_requests, check_cancelled
        self.requests = 0
        self.cache = {}

    def _path(self, tool: str, arguments: dict) -> str:
        """Input: allowlisted tool str and JSON arguments dict. Output: encoded relative API path str."""
        if tool not in RESOURCE_TOOLS or not isinstance(arguments, dict):
            raise ValueError('unsupported resource tool')
        if tool == 'get_documentation_page':
            page = arguments.get('page_id')
            if (set(arguments) != {'page_id'} or not isinstance(page, str)
                    or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', page)):
                raise ValueError('page_id must be a literal documentation identifier')
            return '/tutorial-pages/' + page
        if tool == 'get_operators':
            if set(arguments) - {'search','offset','limit'}:
                raise ValueError('unknown operator filter')
            if (type(arguments.get('offset',0)) is not int or arguments.get('offset',0) < 0
                    or type(arguments.get('limit',50)) is not int or not 1 <= arguments.get('limit',50) <= 50
                    or not isinstance(arguments.get('search',''),str) or len(arguments.get('search','')) > 240):
                raise ValueError('invalid operator page')
            return '/operators'
        if tool in ('get_documentations', 'get_platform_setting_options'):
            if arguments:
                raise ValueError('this resource tool takes no arguments')
            return {'get_operators': '/operators', 'get_documentations': '/tutorials',
                    'get_platform_setting_options': '/simulations'}[tool]
        allowed = {'search', 'limit', 'offset'}
        if tool == 'get_datafields':
            allowed.add('dataset_id')
        if set(arguments) - allowed:
            raise ValueError('unknown resource arguments; scope is owned by the task')
        limit, offset = arguments.get('limit', MAX_PAGE_SIZE), arguments.get('offset', 0)
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE or type(offset) is not int or offset < 0:
            raise ValueError('invalid resource page')
        params = dict(instrumentType=self.scope['instrument_type'], region=self.scope['region'],
                      delay=self.scope['delay'], universe=self.scope['universe'], limit=limit, offset=offset)
        for key, wire in (('search', 'search'), ('dataset_id', 'dataset.id')):
            if key in arguments:
                value = arguments[key]
                if not isinstance(value, str) or len(value) > 240:
                    raise ValueError('resource filter must be a bounded string')
                params[wire] = value
        route = '/data-fields' if tool == 'get_datafields' else '/data-sets'
        return route + '?' + urlencode(params)

    def query(self, tool: str, arguments: dict) -> dict:
        """Input: tool str and filter dict. Output: copied data/provenance/page dict; never platform writes."""
        path = self._path(tool, arguments)
        self.check_cancelled()
        if path in self.cache:
            return self._view(self.cache[path], arguments)
        if self.requests >= self.max_requests:
            raise ValueError('live_resource_request_budget_exhausted')
        self.requests += 1
        method = 'OPTIONS' if tool == 'get_platform_setting_options' else 'GET'
        if method == 'OPTIONS':
            response = self.client.request('OPTIONS', path)
            response.raise_for_status()
            payload = response.json()
        else:
            payload = self.client.get_json(path)
        self.check_cancelled()
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise ValueError('resource response exceeds byte budget; request a smaller page')
        result = dict(tool=tool, payload=payload, scope=deepcopy(self.scope),
                      authority='resource_data_only', source=dict(path=path, method=method,
                      captured_at=datetime.now(timezone.utc).isoformat(),
                      sha256=hashlib.sha256(raw).hexdigest()))
        if tool in ('get_datafields', 'get_datasets'):
            from wqb.data_catalog import _payload_rows_and_count
            rows, count = _payload_rows_and_count(payload)
            offset, limit = arguments.get('offset', 0), arguments.get('limit', MAX_PAGE_SIZE)
            if len(rows) > limit:
                raise ValueError('resource server exceeded requested page size')
            next_offset = offset + len(rows)
            more = next_offset < count if count is not None else len(rows) == limit
            result.update(items=rows, count=count, has_more=more,
                          next_offset=next_offset if more and rows else None,
                          catalog_complete=offset == 0 and count is not None and count == len(rows))
        self.cache[path] = deepcopy(result)
        return self._view(result, arguments)

    def _view(self, result: dict, arguments: dict) -> dict:
        """Input: cached response and local page filters. Output: copied operator page or original resource view."""
        value = deepcopy(result)
        if result['tool'] == 'get_operators':
            payload = result['payload']
            rows = payload if isinstance(payload,list) else payload.get('results',payload.get('operators',[]))
            search = arguments.get('search','').casefold()
            rows = [row for row in rows if search in _text(row).casefold()]
            offset, limit = arguments.get('offset',0), arguments.get('limit',50)
            page = deepcopy(rows[offset:offset+limit])
            value.update(items=page, payload=page, count=len(rows),
                next_offset=offset+limit if offset+limit < len(rows) else None)
        return value
