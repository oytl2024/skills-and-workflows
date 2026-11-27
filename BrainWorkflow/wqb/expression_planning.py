"""Generic AST experiments adapted into existing compiler/tree/package contracts."""
from copy import deepcopy

from wqb.expression_tools import compile_expression, expression_digest
from wqb.template_library import TemplateRecord, template_record_to_dict
from wqb.semantic_contracts import HypothesisCard, InputSlot, OperatorRole


DESIGN_VERSION = 4
MAX_DESIGN_BYTES = 1_000_000
COMPOSITION_CONTRACT = (
    'Read local knowledge and propose economic hypotheses, not claimed facts. Use compile to construct structural '
    'AST expressions, then assemble baseline/treatment design_version=4 experiments into a complete tree. '
    'Nodes: field{dataset_id,field_id}, literal{value}, call{operator,args,kwargs}, unary{operator,input}, '
    'binary{operator,left,right}; all also have kind. No arbitrary Python or formula fragments. '
    'baseline/treatment/repair_recipe are JSON objects, JSON-encoded as strings only on strict model wire. '
    'Hypothesis prose is unrestricted; unknown meaning/polarity/cadence are warnings, not admission gates. '
    'selection may be empty: scripts derive fields. data_characteristics may be empty: scripts fill facts and '
    'retain supplied hypotheses as assumptions. No source-path IDs, semantic whitelist or reviewed-template gate. '
    'Tree nodes use node_id,parent_id,parent_arm_id,design_index,targets{baseline:[],treatment:[]},fallback:[],reverse:{}. '
    'Predeclare all routes/reverses and respect task depth/width budgets. repair_recipe contains finite '
    'wrapper/parameter/setting searches, never code. repair_recipe is {rules:[...]}, at most32 rules, '
    'each grid has1..32 finite scalars. Every rule has edit,grid,target_metric,target_direction; '
    'targets:sharpe/increase,fitness/increase,turnover/decrease. Optional priority(integer),rationale(text), '
    'parameter_direction(increase/decrease/any; default any). wrap adds template AST with exactly one '
    '{kind:parent} hole and optional single {kind:parameter} hole filled by grid values; no field nodes. '
    'parameter adds path to an existing literal AST object, e.g.["args",1], replacing only its value. '
    'Settings edits are decay,truncation,neutralization, with legal finite grids. Example wrapper rule: '
    '{edit:wrap,template:{kind:call,operator:ts_delta,args:[{kind:parent},{kind:parameter}],kwargs:{}},'
    'grid:[5,22],target_metric:fitness,target_direction:increase}. '
    'When technical_exploration_version1 is script-enabled, unknown signatures may be tested as explicit '
    'uncertainty: syntax_valid is not proof of platform behavior or type. Otherwise use supported signatures. '
    'Known syntax/type conflicts remain diagnostics. Validate the full answer and correct technical diagnostics. '
    'Stop/budgets/final submission remain independent. No network or late model decisions after sealing.')


def expression_mode(config: dict) -> bool:
    """Input: versioned config. Output: bool; new-mode opt-in does not reinterpret frozen legacy tasks."""
    value=config.get('expression_tool_version',config.get('research_policy',{}).get('expression_tool_version',0))
    if type(value) is not int or value not in (0,1):
        raise ValueError('expression_tool_version must be integer0 or1')
    return value == 1


def output_schema() -> dict:
    """Input: none. Output: closed generic-plan schema, reusing existing tree routing and JSON-valued AST transport."""
    from wqb.initial_research_planning import _output_schema
    schema=_output_schema(2,include_vector=True)
    schema['properties']['designs']=dict(type='array',maxItems=30,items=dict(type='object',properties=dict(
        design_version=dict(type='integer',enum=[DESIGN_VERSION]),hypothesis=dict(type='string'),
        baseline={},treatment={},repair_recipe={}),
        required=['design_version','hypothesis','baseline','treatment','repair_recipe'],additionalProperties=False))
    return schema


def normalize_design(design: dict) -> dict:
    """Input: generic two-arm design. Output: copied normalized design with script-derived identity; no prose certification."""
    import json
    if not isinstance(design,dict) or set(design)-{'design_version','hypothesis','baseline','treatment','repair_recipe','design_id'}:
        raise ValueError('invalid expression design keys')
    if type(design.get('design_version')) is not int or design['design_version'] != DESIGN_VERSION:
        raise ValueError('unsupported expression design version')
    if not isinstance(design.get('hypothesis'),str) or not all(isinstance(design.get(k),dict) for k in ('baseline','treatment','repair_recipe')):
        raise ValueError('expression design requires prose and structural arms/recipe')
    value=deepcopy(design)
    claimed=value.pop('design_id',None)
    if len(json.dumps(value,allow_nan=False).encode()) > MAX_DESIGN_BYTES:
        raise ValueError('expression design exceeds resource budget')
    value['design_id']='expression_design_'+expression_digest(value)
    if claimed is not None and claimed != value['design_id']:
        raise ValueError('expression design identity changed')
    return value


def selected_fields(designs: list[dict]) -> list[dict]:
    """Input: generic designs. Output: sorted exact field identities derived from structural arm leaves, not prose."""
    found=set()
    def visit(node, depth=0):
        """Input: JSON subtree/depth. Output: None; collect field references with a finite recursion bound."""
        if depth > 32:
            raise ValueError('AST exceeds depth budget')
        if isinstance(node,dict):
            if node.get('kind')=='field':
                pair=(node.get('dataset_id'),node.get('field_id'))
                if any(not isinstance(v,str) or not v for v in pair):
                    raise ValueError('field identity requires dataset_id/field_id')
                found.add(pair)
            for value in node.values(): visit(value,depth+1)
        elif isinstance(node,list):
            for value in node: visit(value,depth+1)
    for design in designs:
        for arm in ('baseline','treatment'): visit(design.get(arm))
    return [dict(dataset_id=d,field_id=f) for d,f in sorted(found)]


def compile_design(design: dict, resources: dict, scope: dict) -> dict:
    """Input: generic design/selected local resources/scope. Output: existing experiment/draft receipt or technical rejections."""
    from wqb.hypothesis_template_compiler import _settings
    try:
        if not expression_mode(resources):
            raise ValueError('generic design requires explicit expression-tool resource contract')
        value=normalize_design(design)
        _settings(resources['settings'],scope)
        digest=expression_digest(dict(design=value,resources=resources,scope=scope))
        arms,drafts,bindings=[],[],{}
        for arm_id in ('baseline','treatment'):
            receipt=compile_expression(value[arm_id],resources,scope)
            if not receipt['valid']:
                return dict(status='rejected',rejections=[dict(item,path=arm_id+item['path'][1:]) for item in receipt['diagnostics']])
            template_id='expression_template_'+expression_digest(dict(design=digest,arm=arm_id,receipt=receipt['receipt_sha256']))
            card=HypothesisCard(data_meaning='Unspecified',mechanism=value['hypothesis'] or 'Unspecified',conditions='Unspecified',
                alternative='Unspecified',prediction='Direction is encoded in the planned expression',
                operator_roles='Frozen technical expression',falsification='Measured tree comparison')
            draft=template_record_to_dict(TemplateRecord(template_id=template_id,hypothesis=value['hypothesis'],
                skeleton=receipt['template']['skeleton'],required_field_types=sorted({slot['field_type'] for slot in receipt['template']['input_slots']}),
                compatible_semantic_tags=[],operator_tags=receipt['used_operators'],status='scout_only',correlation_risk='unknown',
                repair_levers=[],source_paths=sorted(resources.get('source_index',{})),binding_version=2,
                semantic_status='unreviewed',hypothesis_id=value['design_id'],hypothesis_version=1,
                hypothesis_card=card,input_slots=[InputSlot(**slot) for slot in receipt['template']['input_slots']],
                operator_roles=[OperatorRole(operator=name,role='expression',purpose='Planned operator') for name in receipt['used_operators']],
                expression_tool_version=1))
            drafts.append(draft)
            for binding in receipt['binding']['bindings'].values():
                identity=(binding['dataset_id'],binding['field_id'])
                row=next(row for row in resources['field_rows'] if (row['dataset_id'],row['field_id'])==identity)
                bindings['field:'+identity[0]+'/'+identity[1]]=dict(deepcopy(binding),source_paths=deepcopy(row.get('source_paths',[])),evidence_refs=[])
            arms.append(dict(arm_id=arm_id,template_id=template_id,feature=deepcopy(value[arm_id]),
                rationale=value['hypothesis'],settings=deepcopy(resources['settings']),scope=deepcopy(scope),
                binding=deepcopy(receipt['binding'])))
        if arms[0]['binding']['bound_expression']==arms[1]['binding']['bound_expression']:
            raise ValueError('baseline and treatment are duplicate simulations')
        experiment=dict(experiment_id='experiment_'+digest,design_id=value['design_id'],compiler_version='expression-tools-v1',
            compilation_digest=digest,baseline_template_id=drafts[0]['template_id'],arms=arms,changed_dimension='feature',
            controls=[],rejection_criteria='',inconclusive_criteria='',conditions=dict(mode='planned',description='',observable_roles=[]),
            condition_filter_applied=False,prediction_direction='as_planned',orientation=1,context_bindings=bindings,
            context_bindings_digest=expression_digest(bindings),resource_contract_version=2,expression_tool_version=1,
            repair_recipe=deepcopy(value['repair_recipe']))
        return dict(status='compiled',drafts=drafts,experiment=experiment,rejections=[],compilation_digest=digest)
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError) as error:
        return dict(status='rejected',rejections=[dict(code='expression_design',path='$',message=str(error))])
