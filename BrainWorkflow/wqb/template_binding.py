"""Pure snapshot binding. Callers validate source provenance before supplying rows.

No vault access, metadata inference, economic evidence promotion, or evaluation.
Supported grammar: named calls, scalar literals, + - * / and unary +/-. Other
branches fail closed. Availability checks use scope.as_of (timezone-aware ISO).
"""

import ast
import copy
from datetime import datetime
import math
import re
from string import Formatter

from wqb.semantic_contracts import input_slot_from_dict, operator_definition_from_dict
from wqb.resource_evidence import resolve_timing_contract


IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
UNKNOWN_METADATA = {'unknown', 'unavailable', 'unspecified', 'n/a', 'none'}
SCOPE_KEYS = ('instrument_type', 'region', 'delay', 'universe', 'dataset_id')
SCALAR_TYPES = {int: 'INTEGER', float: 'FLOAT', bool: 'BOOLEAN', str: 'STRING'}


class TemplateBindingError(ValueError):
    """Snapshot cannot establish an unambiguous executable binding."""


def parse_kernel(skeleton: str, names: set[str], window: int = 20) -> tuple[ast.expr, dict]:
    """Input: skeleton str, slot names set[str], window int. Output: AST/token map. Parse placeholders safely."""
    if not isinstance(skeleton, str) or not skeleton.strip() or '\n' in skeleton or '\r' in skeleton:
        raise TemplateBindingError('unsupported multiline or empty kernel')
    tokens, parts, occurrences = {}, [], {}
    for literal, name, spec, conversion in Formatter().parse(skeleton):
        parts.append(literal)
        if name is None:
            continue
        if spec or conversion or name not in names | {'window'}:
            raise TemplateBindingError(f'unsupported placeholder: {name}')
        token = '__binding_slot_' + name
        if token in skeleton:
            raise TemplateBindingError('reserved binding identifier')
        tokens[token] = name
        occurrences[token] = occurrences.get(token, 0) + 1
        parts.append(token)
    try:
        node = ast.parse(''.join(parts), mode='eval').body
    except SyntaxError as exc:
        raise TemplateBindingError('invalid placeholder or expression syntax') from exc
    if set(tokens.values()) - {'window'} != names:
        raise TemplateBindingError('kernel must consume every declared input slot')
    call_names = {id(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)}
    for token, count in occurrences.items():
        references = sum(isinstance(item, ast.Name) and item.id == token and id(item) not in call_names
                         for item in ast.walk(node))
        if references != count:
            raise TemplateBindingError('each placeholder must be a standalone AST value node')
    if 'window' in tokens.values() and type(window) is not int:
        raise TemplateBindingError('window placeholder requires INTEGER type')
    for item in ast.walk(node):
        if not isinstance(item, (ast.Call, ast.Name, ast.Load, ast.Constant, ast.BinOp, ast.UnaryOp,
                                 ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.keyword)):
            raise TemplateBindingError(f'unsupported expression grammar: {type(item).__name__}')
        if isinstance(item, ast.Call) and (not isinstance(item.func, ast.Name) or
                                           not IDENTIFIER.fullmatch(item.func.id)):
            raise TemplateBindingError('only named operator calls are supported')
    return node, tokens


def _known(value: object) -> bool:
    """Input: metadata object. Output: bool. Reject explicit missing/unknown facts without inventing replacements."""
    if value is None or value == '' or value == [] or value == {}:
        return False
    return not isinstance(value, str) or value.strip().casefold() not in UNKNOWN_METADATA | {''}


def _available(value: object, as_of: object) -> bool:
    """Input: captured availability/as-of objects. Output: bool. Compare only explicit timezone-aware ISO facts."""
    try:
        available = datetime.fromisoformat(value.replace('Z', '+00:00'))
        cutoff = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
        return available.tzinfo is not None and cutoff.tzinfo is not None and available <= cutoff
    except (AttributeError, TypeError, ValueError):
        return False


def _scope_matches(row: dict, scope: dict) -> bool:
    """Input: field row and requested scope dicts. Output: bool. Match captured tuples, never scope-list cross products."""
    keys = [key for key in SCOPE_KEYS if key in scope]
    scopes = row.get('available_scopes', [row])
    if not isinstance(scopes, list):
        return False
    for captured in scopes:
        if not isinstance(captured, dict):
            continue
        facts = dict(captured)
        if 'dataset_id' in row:
            facts['dataset_id'] = row['dataset_id']
        if all(type(facts.get(key)) is type(scope[key]) and facts.get(key) == scope[key] for key in keys):
            return True
    return False


def _select_field(slot: object, rows: list[dict], scope: dict, resource_version: int = 1) -> dict:
    """Input: InputSlot, snapshot list[dict], scope dict. Output: unique row dict. Select by explicit semantics/type/facts."""
    candidates = []
    for row in rows:
        if row.get('field_type', row.get('type')) != slot.field_type or not _scope_matches(row, scope):
            continue
        description = row.get('field_description', row.get('description', ''))
        tags = row.get('semantic_tags', [])
        if not isinstance(description, str) or not isinstance(tags, list):
            continue
        # Semantics must be explicit tags or complete phrases in the source description, never field IDs.
        if not all(term.casefold() in [tag.casefold() for tag in tags if isinstance(tag, str)] or
                   re.search(r'(?<!\w)' + re.escape(term.casefold()) + r'(?!\w)', description.casefold())
                   for term in slot.required_semantics):
            continue
        candidates.append(row)
    if len(candidates) != 1:
        raise TemplateBindingError(f'{slot.name}: ambiguous or missing semantic/type/scope match ({len(candidates)})')
    row = candidates[0]
    if not isinstance(row.get('dataset_id'), str) or not _known(row['dataset_id']):
        raise TemplateBindingError(f'{slot.name}: missing dataset identity')
    field_id = row.get('field_id', row.get('id'))
    if not isinstance(field_id, str) or not IDENTIFIER.fullmatch(field_id):
        raise TemplateBindingError(f'{slot.name}: invalid field identity')
    if resource_version == 1 and 'timing_contract' in slot.required_metadata:
        raise TemplateBindingError(f'{slot.name}: timing_contract requires resource version 2')
    required = set(slot.required_metadata) | ({'available_at'} if resource_version == 1 else set())
    if slot.field_type == 'VECTOR':
        required.add('vector_grain')
    for key in required:
        if not _known(row.get(key)):
            raise TemplateBindingError(f'{slot.name}: missing required metadata {key}')
        if key in ('units', 'vector_grain', 'available_at') and not isinstance(row[key], str):
            raise TemplateBindingError(f'{slot.name}: {key} requires explicit documented text')
    if (resource_version == 1 or 'available_at' in row) and not _available(row.get('available_at'), scope.get('as_of')):
        raise TemplateBindingError(f'{slot.name}: availability cannot be verified at scope.as_of')
    return row


def _field_timing(row: dict, scope: dict, context: dict | None) -> dict | None:
    """Input: field/scope dicts, context dict or None. Output: receipt dict or None. Verify v2 source-backed timing without IO."""
    if 'timing_contract' not in row:
        if not _available(row.get('available_at'), scope.get('as_of')):
            raise TemplateBindingError('availability cannot be verified at scope.as_of')
        return None
    if not isinstance(context, dict) or not {'source_index', 'source_texts'} <= context.keys():
        raise TemplateBindingError('timing_contract requires source_index/source_texts evidence context')
    result = resolve_timing_contract(row['timing_contract'], row, scope, context['source_index'], context['source_texts'])
    if result['status'] != 'supported':
        raise TemplateBindingError('timing_contract unsupported: ' + result['rejections'][0]['message'])
    return result['value']


def _accepts(actual: str, expected: str) -> bool:
    """Input: actual/expected type str. Output: bool. Permit integer numeric widening only, never bool coercion."""
    return actual == expected or actual == 'INTEGER' and expected == 'FLOAT'


def _check_project_parameter(value: ast.expr, policy: dict) -> None:
    """Input: bound scalar AST/verified project policy dict. Output: None or TemplateBindingError; enforce exact integer subset."""
    try:
        literal = ast.literal_eval(value)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise TemplateBindingError('project window requires a literal integer or bound window') from exc
    if type(literal) is not int or not policy['minimum'] <= literal <= policy['maximum']:
        raise TemplateBindingError('project window is outside verified parameter policy bounds')


def _legacy_bind(template: dict, rows: list[dict], scope: dict) -> dict:
    """Input: legacy template, single field snapshot, scope dict. Output: binding dict. Preserve field/window semantics."""
    if len(rows) != 1:
        raise TemplateBindingError('legacy binding requires exactly one field')
    row = rows[0]
    field_id = row.get('field_id', row.get('id'))
    if not isinstance(field_id, str) or not IDENTIFIER.fullmatch(field_id):
        raise TemplateBindingError('invalid scheduled field identity')
    node, tokens = parse_kernel(template.get('skeleton'), {'field'}, scope.get('window', 20))

    def render(item: ast.AST, raw: bool = False) -> ast.AST:
        """Input: AST, raw bool. Output: AST. Legacy-only default vector reduction; explicit vec calls consume raw field."""
        if isinstance(item, ast.Name) and item.id in tokens:
            if tokens[item.id] == 'window':
                return ast.Constant(value=scope.get('window', 20))
            atom = ast.Name(id=field_id, ctx=ast.Load())
            if row.get('field_type', row.get('type', '')).upper() == 'VECTOR' and not raw:
                return ast.Call(func=ast.Name(id='vec_avg', ctx=ast.Load()), args=[atom], keywords=[])
            return atom
        if isinstance(item, ast.Call):
            item.args = [render(arg, item.func.id.startswith('vec_')) for arg in item.args]
            item.keywords = [ast.keyword(arg=kw.arg, value=render(kw.value, item.func.id.startswith('vec_')))
                             for kw in item.keywords]
        elif isinstance(item, ast.BinOp):
            item.left, item.right = render(item.left), render(item.right)
        elif isinstance(item, ast.UnaryOp):
            item.operand = render(item.operand)
        return item

    node = render(node)
    return dict(bound_expression=ast.unparse(ast.fix_missing_locations(node)),
                bindings={'field': dict(field_id=field_id, dataset_id=row.get('dataset_id'))},
                operator_provenance=[], operator_call_count=sum(isinstance(item, ast.Call) for item in ast.walk(node)))


def bind_template(template: dict, field_rows: list[dict], operator_rows: list[dict], scope: dict, *,
                  resource_contract_version: int = 1, evidence_context: dict | None = None) -> dict:
    """Input: template/scope dicts, field/operator list[dict], resource version int, optional context dict. Output: auditable binding dict.

    Bind fixed kernels without IO. Failure raises TemplateBindingError. Mathematical
    definitions authorize types only, never the hypothesis or an economic claim.
    """
    try:
        if type(resource_contract_version) is not int or resource_contract_version not in (1, 2):
            raise TemplateBindingError('unsupported resource_contract_version')
        return _bind_template(template, field_rows, operator_rows, scope, resource_contract_version, evidence_context)
    except TemplateBindingError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, SyntaxError, RecursionError) as exc:
        raise TemplateBindingError(f'invalid binding contract: {exc}') from exc


def _bind_template(template: dict, field_rows: list[dict], operator_rows: list[dict], scope: dict,
                   resource_version: int = 1, evidence_context: dict | None = None) -> dict:
    """Input: snapshot dictionaries. Output: dict. Validate version and perform conservative typed AST binding."""
    version = template.get('binding_version', 1)
    if type(version) is not int or version not in (1, 2):
        raise TemplateBindingError('unsupported binding_version')
    if version == 1:
        result = _legacy_bind(template, field_rows, scope)
        calls = {item.func.id for item in ast.walk(ast.parse(result['bound_expression'], mode='eval'))
                 if isinstance(item, ast.Call)}
        if any(row.get('operator') in calls and isinstance(row.get('definition_basis'), dict)
               and row['definition_basis'].get('rule_id') == 'ts_delta_project_window' for row in operator_rows):
            raise TemplateBindingError('project window requires binding v2 and explicit resource v2 evidence context')
        return result
    if not isinstance(scope, dict) or not all(_known(scope.get(key)) for key in ('region', 'delay', 'universe')):
        raise TemplateBindingError('v2 requires explicit region/delay/universe scope')
    if type(scope['delay']) is not int or scope['delay'] < 0:
        raise TemplateBindingError('scope.delay must be a nonnegative integer')
    slots = [input_slot_from_dict(row) for row in template.get('input_slots', [])]
    if not slots or len({slot.name for slot in slots}) != len(slots):
        raise TemplateBindingError('v2 requires distinct named input_slots')
    selected = {slot.name: _select_field(slot, field_rows, scope, resource_version) for slot in slots}
    timing = {name: _field_timing(row, scope, evidence_context) for name, row in selected.items()} if resource_version == 2 else {}
    # Even disjoint semantic matches cannot distinguish identical expression IDs across datasets.
    for row in selected.values():
        field_id = row.get('field_id', row.get('id'))
        datasets = {other.get('dataset_id') for other in field_rows if _scope_matches(other, scope)
                    and other.get('field_id', other.get('id')) == field_id}
        if len(datasets) > 1:
            raise TemplateBindingError(f'{field_id}: ambiguous same-name fields across datasets')
    by_slot = {slot.name: slot for slot in slots}
    node, tokens = parse_kernel(template.get('skeleton'), set(by_slot), scope.get('window', 20))
    provenance, consumed = [], set()
    definitions, receipts = {}, {}

    def definition(name: str) -> dict:
        """Input: operator name str. Output: dict. Require one documented typed definition from supplied snapshot."""
        if name in definitions:
            return definitions[name]
        matches = [row for row in operator_rows if row.get('operator') == name]
        if len(matches) != 1 or not isinstance(matches[0].get('definition'), dict):
            raise TemplateBindingError(f'{name}: missing or ambiguous documented definition')
        row = matches[0]
        basis = row.get('definition_basis')
        project = isinstance(basis, dict) and basis.get('rule_id') == 'ts_delta_project_window'
        if project or resource_version == 2 and basis is not None:
            if resource_version != 2 or not isinstance(evidence_context, dict) or not {
                    'source_index', 'source_texts'} <= evidence_context.keys():
                raise TemplateBindingError('derived operator requires explicit resource v2 and evidence context')
            from wqb.resource_evidence import resolve_operator_definition
            result = resolve_operator_definition(row, evidence_context['source_index'],
                evidence_context['source_texts'], resource_contract_version=2)
            if result['status'] != 'supported':
                raise TemplateBindingError(f'{name}: unsupported definition basis: {result["rejections"]}')
            receipts[name] = result['value']
        definitions[name] = operator_definition_from_dict(row['definition'])
        return definitions[name]

    for slot in slots:
        if slot.reduction is None:
            continue
        contract = definition(slot.reduction['operator'])
        if slot.field_type != 'VECTOR' or contract['input_types'] != ['VECTOR'] or contract['output_type'] != 'MATRIX':
            raise TemplateBindingError(f'{slot.name}: reduction requires documented VECTOR to MATRIX signature')
        parameters = {parameter['name']: parameter for parameter in contract['parameters'][1:]}
        for key, value in slot.reduction['parameters'].items():
            parameter = parameters.get(key)
            if parameter is None:
                raise TemplateBindingError(f'{slot.name}: unknown reduction parameter {key}')
            if not _accepts(SCALAR_TYPES.get(type(value)), parameter['type']):
                raise TemplateBindingError(f'{slot.name}.{key}: reduction parameter type disagrees with signature')

    def render(item: ast.expr, expected: str | None = None) -> tuple[ast.expr, str]:
        """Input: expression AST and optional expected type str. Output: (bound AST, type str). Type-check every call."""
        if isinstance(item, ast.Name):
            if item.id not in tokens:
                raise TemplateBindingError(f'unknown identifier: {item.id}')
            name = tokens[item.id]
            if name == 'window':
                return ast.Constant(value=scope.get('window', 20)), 'INTEGER'
            slot, row = by_slot[name], selected[name]
            atom = ast.Name(id=row.get('field_id', row.get('id')), ctx=ast.Load())
            if slot.reduction and expected != 'VECTOR':
                reducer = slot.reduction
                contract = definition(reducer['operator'])
                if contract['input_types'] != ['VECTOR'] or contract['output_type'] != 'MATRIX' or slot.field_type != 'VECTOR':
                    raise TemplateBindingError(f'{name}: reduction requires documented VECTOR to MATRIX signature')
                call = ast.Call(func=ast.Name(id=reducer['operator'], ctx=ast.Load()), args=[item],
                                keywords=[ast.keyword(arg=key, value=ast.Constant(value=value))
                                          for key, value in reducer['parameters'].items()])
                return render(call)
            consumed.add(name)
            return atom, slot.field_type
        if isinstance(item, ast.Constant):
            kind = SCALAR_TYPES.get(type(item.value))
            if kind is None or type(item.value) is float and not math.isfinite(item.value):
                raise TemplateBindingError('unsupported or nonfinite scalar literal')
            return item, kind
        if isinstance(item, ast.UnaryOp):
            operand, kind = render(item.operand)
            if kind not in ('MATRIX', 'INTEGER', 'FLOAT'):
                raise TemplateBindingError('unary arithmetic requires numeric type')
            return ast.UnaryOp(op=item.op, operand=operand), kind
        if isinstance(item, ast.BinOp):
            left, left_type = render(item.left)
            right, right_type = render(item.right)
            if left_type not in ('MATRIX', 'INTEGER', 'FLOAT') or right_type not in ('MATRIX', 'INTEGER', 'FLOAT'):
                raise TemplateBindingError('binary arithmetic requires numeric matrix/scalar types')
            kind = 'MATRIX' if 'MATRIX' in (left_type, right_type) else 'FLOAT'
            return ast.BinOp(left=left, op=item.op, right=right), kind
        if not isinstance(item, ast.Call):
            raise TemplateBindingError('unsupported expression branch')
        name = item.func.id
        contract = definition(name)
        parameters = contract['parameters']
        if len(item.args) > len(parameters):
            raise TemplateBindingError(f'{name}: too many positional parameters')
        supplied = {parameter['name']: arg for parameter, arg in zip(parameters, item.args)}
        for kw in item.keywords:
            if kw.arg is None or kw.arg in supplied or kw.arg not in {p['name'] for p in parameters}:
                raise TemplateBindingError(f'{name}: unknown or duplicate parameter {kw.arg}')
            supplied[kw.arg] = kw.value
        receipt = receipts.get(name)
        policy = receipt.get('parameter_policy') if receipt else None
        entry = dict(operator=name, evidence_refs=copy.deepcopy(contract['evidence_refs']))
        if receipt is not None:
            entry['definition_receipt'] = copy.deepcopy(receipt)
        provenance.append(entry)
        bound = {}
        for index, parameter in enumerate(parameters):
            key = parameter['name']
            if key not in supplied:
                if parameter['required'] or index < len(contract['input_types']):
                    raise TemplateBindingError(f'{name}: missing required parameter {key}')
                if policy is not None and key == policy['parameter']:
                    _check_project_parameter(ast.Constant(value=parameter.get('default')), policy)
                continue
            arg = supplied[key]
            value, actual = render(arg, parameter['type'])
            if not _accepts(actual, parameter['type']):
                raise TemplateBindingError(f'{name}.{key}: type {actual} does not match {parameter["type"]}')
            if policy is not None and key == policy['parameter']:
                _check_project_parameter(value, policy)
            if parameter['type'] == 'VECTOR' and isinstance(arg, ast.Name) and arg.id in tokens:
                reduction = by_slot[tokens[arg.id]].reduction
                if reduction and (reduction['operator'] != name or contract['output_type'] != 'MATRIX'):
                    raise TemplateBindingError('explicit reduction disagrees with slot reduction')
                if reduction:
                    for param_name, param_value in reduction['parameters'].items():
                        explicit = supplied.get(param_name)
                        default = next((p.get('default') for p in parameters if p['name'] == param_name), None)
                        if not (isinstance(explicit, ast.Constant) and type(explicit.value) is type(param_value)
                                and explicit.value == param_value) and not (explicit is None and default == param_value):
                            raise TemplateBindingError('explicit reduction parameters disagree with slot reduction')
            bound[key] = value
        args = [bound[p['name']] for p in parameters[:len(item.args)]]
        keywords = [ast.keyword(arg=kw.arg, value=bound[kw.arg]) for kw in item.keywords]
        return ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=args, keywords=keywords), contract['output_type']

    bound, output_type = render(node)
    if consumed != set(by_slot):
        raise TemplateBindingError('kernel must consume every input slot as an actual field reference')
    if output_type != 'MATRIX':
        raise TemplateBindingError('kernel must produce MATRIX output')
    bindings = {}
    for slot in slots:
        row = selected[slot.name]
        metadata = set(slot.required_metadata) | ({'available_at'} if resource_version == 1 or 'available_at' in row else set())
        if timing.get(slot.name) is not None:
            metadata.add('timing_contract')
        if slot.field_type == 'VECTOR':
            metadata.add('vector_grain')
        bindings[slot.name] = dict(field_id=row.get('field_id', row.get('id')), dataset_id=row.get('dataset_id'),
                                   field_type=slot.field_type, role=slot.role,
                                   required_semantics=list(slot.required_semantics),
                                   metadata={key: copy.deepcopy(row[key]) for key in sorted(metadata)},
                                   reduction=copy.deepcopy(slot.reduction))
        if timing.get(slot.name) is not None:
            bindings[slot.name]['timing_receipt'] = timing[slot.name]
    return dict(bound_expression=ast.unparse(ast.fix_missing_locations(bound)), bindings=bindings,
                operator_provenance=provenance, operator_call_count=len(provenance))
