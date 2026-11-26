"""Pure structural expression builder sharing the existing typed AST binder."""
import ast
from copy import deepcopy
import hashlib
import json
import math

from wqb.template_binding import bind_technical_template, IDENTIFIER, TemplateBindingError


EXPRESSION_TOOL_VERSION = 1
MAX_AST_NODES = 512
MAX_AST_DEPTH = 32
MAX_AST_BYTES = 64000
BINARY = {'+': ast.Add, '-': ast.Sub, '*': ast.Mult, '/': ast.Div}
UNARY = {'+': ast.UAdd, '-': ast.USub}


class ExpressionConstructionError(ValueError):
    """Local technical error with a stable node path, never a knowledge approval decision."""
    def __init__(self, code: str, path: str, message: str):
        """Input: diagnostic strings. Output: exception carrying machine-readable location and code."""
        super().__init__(message)
        self.code, self.path = code, path


def expression_digest(value: object) -> str:
    """Input: finite JSON. Output: deterministic SHA256, without runtime authority."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def expression_ast(expression: str, resources: dict) -> dict:
    """Input: frozen expression string/resource rows. Output: structural AST; parse only, never evaluate Python."""
    from wqb.template_binding import parse_kernel
    root,_=parse_kernel(expression,set())
    fields={}
    for row in resources['field_rows']:
        name=row['field_id']
        if name in fields and fields[name] != row['dataset_id']:
            raise ValueError('ambiguous expression field identifier')
        fields[name]=row['dataset_id']
    def convert(node):
        """Input: parsed supported AST. Output: JSON node with exact frozen field identity."""
        if isinstance(node,ast.Name) and node.id in fields:
            return dict(kind='field',dataset_id=fields[node.id],field_id=node.id)
        if isinstance(node,ast.Constant):
            return dict(kind='literal',value=node.value)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
            return dict(kind='call',operator=node.func.id,args=[convert(v) for v in node.args],
                kwargs={v.arg:convert(v.value) for v in node.keywords})
        if isinstance(node,ast.UnaryOp):
            return dict(kind='unary',operator=next(k for k,v in UNARY.items() if isinstance(node.op,v)),input=convert(node.operand))
        if isinstance(node,ast.BinOp):
            return dict(kind='binary',operator=next(k for k,v in BINARY.items() if isinstance(node.op,v)),left=convert(node.left),right=convert(node.right))
        raise ValueError('unsupported expression node or unknown field')
    return convert(root)


def compile_expression(request: dict, resources: dict, scope: dict) -> dict:
    """Input: structural AST, field/operator snapshot and scope dicts. Output: typed expression receipt or node diagnostics; no IO."""
    selected, slots, nodes = {}, [], 0

    def fail(path, message, code='invalid_ast'):
        """Input: node path/message/code strings. Output: raised local diagnostic."""
        raise ExpressionConstructionError(code, path, message)

    def build(node, path='$', depth=0):
        """Input: JSON node/path/depth. Output: safe Python expression AST for the existing supported grammar."""
        nonlocal nodes
        nodes += 1
        if nodes > MAX_AST_NODES or depth > MAX_AST_DEPTH:
            fail(path, 'Expression exceeds structural resource bound', 'ast_budget')
        if not isinstance(node, dict):
            fail(path, 'Expected a structural node object')
        kind = node.get('kind')
        keys = {'field': {'kind','dataset_id','field_id'}, 'literal': {'kind','value'},
            'call': {'kind','operator','args','kwargs'}, 'unary': {'kind','operator','input'},
            'binary': {'kind','operator','left','right'}}
        if kind not in keys or set(node) != keys[kind]:
            fail(path, 'Unknown node kind or missing/extra keys')
        if kind == 'field':
            pair = (node['dataset_id'], node['field_id'])
            if any(not isinstance(v,str) or not v for v in pair):
                fail(path, 'Expected exact dataset and field identity', 'field_identity')
            if pair not in selected:
                matches = [row for row in resources['field_rows'] if row.get('dataset_id') == pair[0]
                    and row.get('field_id',row.get('id')) == pair[1]
                    and all(type(row.get(k)) is type(scope[k]) and row.get(k) == scope[k]
                        for k in ('region','delay','universe'))]
                if len(matches) != 1:
                    fail(path, 'Missing/ambiguous field identity or exact scope', 'field_identity')
                name = 'f' + str(len(slots))
                selected[pair] = name
                slots.append(dict(name=name, role='expression_input', field_type=matches[0].get('field_type',matches[0].get('type')),
                    required_semantics=['field:' + pair[0] + '/' + pair[1]], required_metadata=[]))
            return ast.Name(id='{' + selected[pair] + '}', ctx=ast.Load())
        if kind == 'literal':
            value = node['value']
            if type(value) not in (int,float,str,bool) or type(value) is float and not math.isfinite(value):
                fail(path, 'Expected finite scalar literal', 'literal_type')
            return ast.Constant(value=value)
        if kind == 'call':
            name = node['operator']
            if not isinstance(name,str) or not IDENTIFIER.fullmatch(name) or name.startswith('__'):
                fail(path, 'Expected a named operator', 'operator_signature')
            if not isinstance(node['args'],list) or not isinstance(node['kwargs'],dict):
                fail(path, 'Expected args array and kwargs object')
            if any(not isinstance(k,str) or not IDENTIFIER.fullmatch(k) for k in node['kwargs']):
                fail(path, 'Invalid named parameter')
            return ast.Call(func=ast.Name(id=name,ctx=ast.Load()),
                args=[build(value,path+'.args['+str(i)+']',depth+1) for i,value in enumerate(node['args'])],
                keywords=[ast.keyword(arg=k,value=build(value,path+'.kwargs.'+k,depth+1)) for k,value in node['kwargs'].items()])
        operators = UNARY if kind == 'unary' else BINARY
        if node['operator'] not in operators:
            fail(path, 'Unsupported arithmetic operator')
        if kind == 'unary':
            return ast.UnaryOp(op=operators[node['operator']](),operand=build(node['input'],path+'.input',depth+1))
        return ast.BinOp(left=build(node['left'],path+'.left',depth+1),op=operators[node['operator']](),
            right=build(node['right'],path+'.right',depth+1))

    try:
        if len(json.dumps(request,allow_nan=False).encode()) > MAX_AST_BYTES:
            fail('$','Expression input exceeds byte budget','ast_budget')
        node = build(request)
        skeleton = ast.unparse(ast.fix_missing_locations(node))
        template = dict(binding_version=2,skeleton=skeleton,input_slots=slots)
        binding = bind_technical_template(template,resources['field_rows'],resources['operator_rows'],scope)
        result = dict(valid=True,expression_tool_version=EXPRESSION_TOOL_VERSION,expression=binding['bound_expression'],
            ast=deepcopy(request),output_type='MATRIX',template=template,binding=binding,
            used_fields=[dict(dataset_id=pair[0],field_id=pair[1]) for pair in selected],
            used_operators=sorted({row['operator'] for row in binding['operator_provenance']}),warnings=[],diagnostics=[])
        result['receipt_sha256'] = expression_digest(result)
        return result
    except ExpressionConstructionError as error:
        return dict(valid=False,diagnostics=[dict(code=error.code,path=error.path,message=str(error))])
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,TemplateBindingError) as error:
        return dict(valid=False,diagnostics=[dict(code='technical_binding',path='$',message=str(error))])
