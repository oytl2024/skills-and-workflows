"""Finite frozen AST/parameter Repair using the shared technical expression compiler."""
from copy import deepcopy
import json
import math

from wqb.expression_tools import compile_expression, expression_ast, expression_digest
from wqb.repair_trace import TARGET_DIRECTIONS


POLICY_VERSION = 3
MAX_RULES = 32
MAX_GRID = 32
MAX_POLICY_BYTES = 1_000_000
SETTING_EDITS = {'decay','truncation','neutralization'}


def _scalar(value):
    """Input: JSON scalar. Output: bool; never accept nonfinite search values or executable objects."""
    return type(value) in (str,bool,int,float) and (type(value) is not float or math.isfinite(value))


def compile_policy(resources: dict, recipes: list, base_policy: dict | None = None) -> dict:
    """Input: selected resources/finite proposals/optional default settings policy. Output: frozen technical search policy."""
    rules=[]
    proposed=[deepcopy(rule) for rule in (base_policy or {}).get('rules',[])]
    for recipe in recipes:
        if not isinstance(recipe,dict) or set(recipe)-{'rules'} or not isinstance(recipe.get('rules',[]),list):
            raise ValueError('Repair recipe must contain a finite rules array')
        proposed.extend(deepcopy(recipe.get('rules',[])))
    for item in proposed:
        rule={key:deepcopy(item[key]) for key in ('edit','grid','template','path','trigger') if key in item}
        rule.update(priority=item.get('priority',0),target_metric=item.get('target_metric','fitness'),
            target_direction=item.get('target_direction','increase'),parameter_direction=item.get('parameter_direction','any'),
            rationale=item.get('rationale',''),requires={},evidence_refs=[],basis='project_hypothesis',
            effect='planned_ast_edit' if item.get('edit') in ('wrap','parameter') else 'planned_setting_edit')
        rule['rule_id']='expression_rule_'+expression_digest(rule)
        if not any(other['rule_id']==rule['rule_id'] for other in rules): rules.append(rule)
    context=dict(scope=deepcopy(resources.get('scope',resources.get('evidence_pack',{}).get('scope'))),
        field_rows=[{key:deepcopy(row[key]) for key in ('dataset_id','field_id','field_type','region','delay','universe','instrument_type') if key in row}
                    for row in resources['field_rows']],
        operator_rows=[{key:deepcopy(row[key]) for key in ('operator','definition','definition_basis') if key in row}
                       for row in resources['operator_rows'] if isinstance(row.get('definition'),dict) or resources.get('technical_exploration_version') == 1])
    if resources.get('technical_exploration_version') == 1:
        context['technical_exploration_version']=1
    return validate_policy(dict(schema_version=POLICY_VERSION,expression_tool_version=1,rulebook_id='frozen-expression-search-v1',
        rules=rules,traits={},resources=context))


def validate_policy(policy: dict) -> dict:
    """Input: claimed search policy. Output: validated copy; only structural/execution and finite-space constraints."""
    if (not isinstance(policy,dict) or type(policy.get('schema_version')) is not int or policy['schema_version']!=POLICY_VERSION or
            type(policy.get('expression_tool_version')) is not int or policy['expression_tool_version']!=1 or not isinstance(policy.get('resources'),dict) or
            not isinstance(policy.get('rules'),list) or len(policy['rules'])>MAX_RULES or not isinstance(policy.get('traits'),dict)):
        raise ValueError('invalid expression Repair policy')
    if len(json.dumps(policy,allow_nan=False).encode())>MAX_POLICY_BYTES:
        raise ValueError('Repair policy exceeds byte budget')
    result=deepcopy(policy)
    seen=set()
    for rule in result['rules']:
        if (rule.get('edit') not in SETTING_EDITS|{'wrap','parameter'} or
                rule.get('target_metric') not in TARGET_DIRECTIONS or
                rule.get('target_direction')!=TARGET_DIRECTIONS[rule['target_metric']] or
                type(rule.get('priority')) is not int or rule.get('parameter_direction') not in ('increase','decrease','any') or
                not isinstance(rule.get('grid'),list) or not 1<=len(rule['grid'])<=MAX_GRID or
                any(not _scalar(value) for value in rule['grid']) or rule.get('rule_id') in seen):
            raise ValueError('invalid finite Repair rule/target/grid')
        if rule['edit']=='wrap' and not isinstance(rule.get('template'),dict):
            raise ValueError('wrapper requires structural template')
        if rule['edit']=='parameter' and (not isinstance(rule.get('path'),list) or not rule['path'] or
                any(type(key) not in (int,str) for key in rule['path'])):
            raise ValueError('parameter edit requires a structural literal path')
        if 'trigger' in rule:
            from wqb.repair_search import _metric_rule
            _metric_rule(rule)
        seen.add(rule['rule_id'])
    result['rules'].sort(key=lambda rule:(rule['priority'],rule['rule_id']))
    return result


def _wrap(template, parent, value):
    """Input: wrapper AST/parent/scalar. Output: substituted AST with exactly one preserved parent and no new fields."""
    counts=dict(parent=0,parameter=0)
    def replace(node,depth=0):
        """Input: template node/depth. Output: copied substitution; reject field injection and unbounded nesting."""
        if depth>32: raise ValueError('wrapper exceeds depth budget')
        if isinstance(node,dict):
            kind=node.get('kind')
            if kind in counts:
                if set(node)!={'kind'}: raise ValueError('invalid wrapper hole')
                counts[kind]+=1
                return deepcopy(parent) if kind=='parent' else dict(kind='literal',value=value)
            if kind=='field': raise ValueError('Repair wrapper cannot introduce a field')
            return {key:replace(part,depth+1) for key,part in node.items()}
        if isinstance(node,list): return [replace(part,depth+1) for part in node]
        return deepcopy(node)
    output=replace(template)
    if counts['parent']!=1 or counts['parameter']>1:
        raise ValueError('wrapper must preserve exactly one complete parent subtree')
    return output


def _parameter_value(parent, path):
    """Input: AST/path. Output: existing scalar, including parsed signed numeric literals; never evaluate expressions."""
    current=parent
    for key in path: current=current[key]
    if isinstance(current,dict) and set(current)=={'kind','value'} and current['kind']=='literal':
        return current['value']
    if (isinstance(current,dict) and set(current)=={'kind','operator','input'} and current['kind']=='unary'
            and current['operator'] in ('+','-') and isinstance(current['input'],dict)
            and set(current['input'])=={'kind','value'} and current['input']['kind']=='literal'
            and type(current['input']['value']) in (int,float)):
        return current['input']['value'] * (-1 if current['operator']=='-' else 1)
    raise ValueError('parameter path must select an existing scalar literal')


def _parameter(parent, path, value):
    """Input: parent AST/path/scalar. Output: AST with exactly one existing literal changed, never a field/operator."""
    result=deepcopy(parent)
    _parameter_value(result,path)
    current=result
    for key in path[:-1]: current=current[key]
    current[path[-1]]=dict(kind='literal',value=value)
    return result


def prepare_search(parent: dict, history: list, allowance: int, policy: dict) -> dict:
    """Input: measured incumbent/history/allowance/frozen policy. Output: existing deterministic plan schema; no IO/model/API."""
    from wqb.cli import simulation_identity_hash
    from wqb.repair_identity import identity_hash_scheme
    from wqb.repair_search import _used_identities,ECONOMIC_CONTEXT_KEYS,_failure_evidence,_trigger_evidence
    from wqb.hypothesis_template_compiler import _settings
    result=dict(schema_version=1,planner_kind='deterministic',planner_version=3,status='blocked',variants=[],skipped=[],stop_reason='')
    try:
        frozen=validate_policy(policy)
        if not isinstance(parent,dict) or not parent.get('alpha_id') or not identity_hash_scheme(parent):
            raise ValueError('invalid measured parent identity')
        if type(allowance) is not int or not 0<=allowance<=8 or not isinstance(history,list):
            raise ValueError('invalid allowance/history')
        used=_used_identities(parent,history)
        result['evidence_digest']=expression_digest(dict(parent=parent,history=history,policy=frozen,allowance=allowance))
        if frozen.get('stop') or parent.get('hard_pass') or allowance==0:
            return dict(result,status='stopped',stop_reason='stopped' if frozen.get('stop') else 'already_qualified' if parent.get('hard_pass') else 'allowance_exhausted')
        if len(history)>=sum(len(rule['grid']) for rule in frozen['rules']):
            return dict(result,status='exhausted',stop_reason='search_space_exhausted',remaining_candidates=0)
        context=frozen['resources']
        source=expression_ast(parent['expression'],context)
        for rule in frozen['rules']:
            if not isinstance(parent.get('metrics'),dict) or not isinstance(parent['metrics'].get(rule['target_metric']),(int,float)):
                result['skipped'].append(dict(rule_id=rule['rule_id'],reason='target_unmeasured')); continue
            if 'trigger' in rule:
                evidence=_trigger_evidence(rule,parent,_failure_evidence(parent))
                if not evidence['activated']:
                    result['skipped'].append(dict(rule_id=rule['rule_id'],reason='trigger_not_observed')); continue
            for ordinal,value in enumerate(rule['grid']):
                try:
                    settings=deepcopy(parent['settings'])
                    binding=None
                    if rule['edit']=='wrap': node=_wrap(rule['template'],source,value)
                    elif rule['edit']=='parameter':
                        current=_parameter_value(source,rule['path'])
                        direction=rule['parameter_direction']
                        if direction!='any' and not (value>current if direction=='increase' else value<current): continue
                        node=_parameter(source,rule['path'],value)
                    else:
                        node=source
                        current=settings.get(rule['edit'])
                        direction=rule['parameter_direction']
                        if direction!='any' and not (value>current if direction=='increase' else value<current): continue
                        settings[rule['edit']]=value
                        _settings(settings,context['scope'])
                    compiled=compile_expression(node,context,context['scope'])
                    if not compiled['valid']: raise ValueError(json.dumps(compiled['diagnostics']))
                    expression=compiled['expression']
                    identity=simulation_identity_hash(expression,settings)
                    if identity in used: continue
                    used.add(identity)
                    edit='transform' if rule['edit'] in ('wrap','parameter') else rule['edit']
                    decision=dict(action='test',edit=edit,value=value if type(value) in (int,float) or edit!='transform' else ordinal,
                        parameter_value=value,rule_id=rule['rule_id'],effect=rule['effect'],target_metric=rule['target_metric'],
                        target_direction=rule['target_direction'],basis='project_hypothesis',rationale=rule['rationale'],
                        evidence_refs=[],applicability='Frozen structural recipe; unknown data properties remain unknown',
                        parent_alpha_id=parent['alpha_id'],parent_expression_hash=parent['expression_hash'])
                    variant=dict(expression=expression,settings=settings,expression_hash=identity,simulation_identity=identity,
                        parent_alpha_id=parent['alpha_id'],parent_expression_hash=parent['expression_hash'],
                        repair_action='deterministic_'+rule['edit'],decision=decision,binding=compiled['binding'])
                    variant.update({key:deepcopy(parent[key]) for key in ECONOMIC_CONTEXT_KEYS if key in parent})
                    result['variants'].append(variant)
                except (ValueError,TypeError,KeyError,IndexError,AttributeError) as error:
                    result['skipped'].append(dict(rule_id=rule['rule_id'],value=value,reason='technical_edit_rejected',detail=str(error)[:500]))
        result['remaining_candidates']=max(0,len(result['variants'])-allowance)
        result['variants']=result['variants'][:allowance]
        return dict(result,status='validated' if result['variants'] else 'exhausted',
            stop_reason='' if result['variants'] else 'search_space_exhausted')
    except (ValueError,TypeError,KeyError,IndexError,AttributeError) as error:
        return dict(result,stop_reason='invalid_expression_search',reason=str(error))
