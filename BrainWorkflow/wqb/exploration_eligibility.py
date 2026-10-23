"""Pure compiler proposals and raw-certified attachments, never publication or live authority."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from wqb.hypothesis_design import compile_hypothesis_design
from wqb.knowledge_paths import machine_resource_path
from wqb.lockfile import json_lock_transition_guard
from wqb.runtime_control import _write
from wqb.semantic_compilation import _material, _safe


EXPLORATION_VERSION = 1
EXPLORATION_POLICY_VERSION = 1
MAX_INDEX_BYTES = 16_000_000
RECEIPT_KEYS = {'schema_version', 'status', 'knowledge_status', 'compiler_input',
                'compiled', 'content_sha256'}
CERTIFICATE_KEYS = {'schema_version', 'kind', 'owning_run', 'policy', 'scope',
                    'resources_sha256', 'source_index_sha256', 'sources', 'content_sha256'}


def _digest(value: object) -> str:
    """Input: finite JSON object. Output: str digest; bind source bytes and compiled evidence."""
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def validate_exploration(design: dict, resources: dict, scope: dict) -> dict:
    """Input: normalized design/resources/scope dicts. Output: pure compiler proposal receipt.

    Supplied source consistency is not independent raw certification. This pure
    fixture/compiler eligibility cannot authorize operational attachment, model
    invocation, platform requests, reviewed release or final submission.
    """
    inputs = deepcopy(dict(design=design, resources=resources, scope=scope))
    compiled = compile_hypothesis_design(**inputs)
    if compiled.get('status') != 'compiled':
        raise ValueError('exploration compilation rejected: ' + json.dumps(compiled.get('rejections')))
    arms = compiled['experiment']['arms']
    if len(arms) != 2 or {row['arm_id'] for row in arms} != {'baseline', 'treatment'}:
        raise ValueError('exploration requires a complete baseline/treatment pair')
    if any(row.get('semantic_status') != 'unreviewed' or row.get('status') != 'scout_only'
           for row in compiled['drafts']):
        raise ValueError('compiler exploration drafts cannot grant reviewed authority')
    receipt = dict(schema_version=EXPLORATION_VERSION, status='exploration_eligible',
                   knowledge_status='exploratory', compiler_input=inputs, compiled=compiled)
    receipt['content_sha256'] = _digest(receipt)
    return receipt


def verify_exploration(receipt: dict) -> dict:
    """Input: claimed receipt dict. Output: rebuilt dict; reject schema, source or output tampering."""
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_KEYS:
        raise ValueError('invalid exploration receipt schema')
    if type(receipt['schema_version']) is not int or receipt['schema_version'] != EXPLORATION_VERSION:
        raise ValueError('unsupported exploration receipt version')
    inputs = receipt['compiler_input']
    if not isinstance(inputs, dict) or set(inputs) != {'design', 'resources', 'scope'}:
        raise ValueError('invalid exploration compiler inputs')
    rebuilt = validate_exploration(**inputs)
    if _digest(rebuilt) != _digest(receipt):
        raise ValueError('exploration receipt differs from compiler proposal')
    return rebuilt


def match_exploration(receipts: list[dict], design: dict, scope: dict, resources: dict) -> dict | None:
    """Input: receipts list, normalized design/scope/resources dicts. Output: compatible receipt or None.

    Stable design IDs include source and semantic role contracts. Do not infer
    equivalent economic mechanisms from matching prose or field names.
    """
    if not isinstance(receipts, list):
        raise ValueError('exploration library must be a list')
    matches = []
    for claimed in receipts:
        receipt = verify_exploration(claimed)
        inputs = receipt['compiler_input']
        if inputs['scope'] == scope and inputs['design'] == design and inputs['resources'] == resources:
            matches.append(receipt)
    return min(matches, key=lambda row: row['content_sha256']) if matches else None


def _run_context(run: Path, knowledge_root: Path, scope: dict) -> tuple[dict, dict]:
    """Input: run/vault Paths and scope dict. Output: owner/policy dicts; require frozen new-run opt-in."""
    for path in (Path(run), Path(knowledge_root)):
        if any(parent.is_symlink() or parent.is_junction() for parent in (path, *path.parents)):
            raise ValueError('exploration roots cannot traverse links')
    root = Path(run).resolve(strict=True)
    vault = Path(knowledge_root).resolve(strict=True)
    try:
        raw = _safe(root, 'run_manifest.json').read_bytes()
        manifest = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise ValueError('exploration requires an owning frozen Start manifest') from exc
    if not isinstance(manifest, dict):
        raise ValueError('invalid owning run manifest')
    snapshot = manifest.get('start_snapshot')
    if not isinstance(snapshot, dict):
        raise ValueError('old run has no frozen exploration Start contract')
    policy = snapshot.get('research_policy')
    if (not exploration_scout_enabled(policy) or policy.get('paired_scout') is not True
            or type(policy.get('exploration_policy_version')) is not int
            or policy['exploration_policy_version'] != EXPLORATION_POLICY_VERSION):
        raise ValueError('owning run requires explicit versioned exploration opt-in')
    if 'semantic_release' in snapshot or 'operational_resource_context' in snapshot:
        raise ValueError('exploration cannot attach to a mixed reviewed Start context')
    if (manifest.get('run_id') != root.name or _digest(manifest.get('selected_scope')) != _digest(scope)
            or _digest(snapshot.get('selected_scope')) != _digest(scope)
            or not isinstance(manifest.get('knowledge_root'), str)
            or Path(manifest['knowledge_root']).resolve() != vault):
        raise ValueError('exploration owning run, scope or vault mismatch')
    # Result attachments may grow; only frozen Start identity/scope/policy is authority.
    start_context = dict(run_id=root.name, knowledge_root=str(vault), selected_scope=scope,
        created_at=manifest.get('created_at'), selected_option_id=manifest.get('selected_option_id'),
        research_policy=policy)
    owner = dict(run_id=root.name, path=str(root), knowledge_root=str(vault),
                 start_context_sha256=_digest(start_context))
    return owner, deepcopy(policy)


def _resource_certificate(run: Path, knowledge_root: Path, resources: dict, scope: dict) -> dict:
    """Input: run/vault Paths, resource/scope dicts. Output: raw-verified bound certificate dict, no writes."""
    owner, policy = _run_context(run, knowledge_root, scope)
    vault = Path(owner['knowledge_root'])
    canonical = machine_resource_path(vault, 'source_index')
    index = _safe(vault, canonical.relative_to(vault).as_posix())
    if index.stat().st_size > MAX_INDEX_BYTES:
        raise ValueError('exploration source index exceeds read bound')
    raw = index.read_bytes()
    registered = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get('path'), str) or row['path'] in registered:
            raise ValueError('invalid or duplicate canonical source index row')
        registered[row['path']] = row
    requested = resources.get('source_index')
    texts = resources.get('source_texts')
    if (not isinstance(requested, dict) or not requested or not isinstance(texts, dict)
            or set(requested) != set(texts)):
        raise ValueError('exploration requires exact indexed source texts')
    sources = {}
    for path, row in sorted(requested.items()):
        if _digest(row) != _digest(registered.get(path)) or row.get('path') != path:
            raise ValueError('requested source differs from canonical registration')
        verified, text = _material(vault, registered[path])
        if text != texts[path]:
            raise ValueError('exploration source text differs from actual raw bytes')
        sources[path] = verified
    if index.read_bytes() != raw or _run_context(run, knowledge_root, scope) != (owner, policy):
        raise ValueError('exploration Start context or index changed during certification')
    certificate = dict(schema_version=EXPLORATION_VERSION, kind='exploration_resources',
        owning_run=owner, policy=policy, scope=deepcopy(scope), resources_sha256=_digest(resources),
        source_index_sha256=hashlib.sha256(raw).hexdigest(), sources=sources)
    certificate['content_sha256'] = _digest(certificate)
    return certificate


def _verify_certificate(certificate: dict, resources: dict, scope: dict) -> dict:
    """Input: certificate/resource/scope dicts. Output: copied context; pure checks do not grant IO authority."""
    if not isinstance(certificate, dict) or set(certificate) != CERTIFICATE_KEYS:
        raise ValueError('invalid exploration resource certificate')
    payload = {key: value for key, value in certificate.items() if key != 'content_sha256'}
    if (type(certificate['schema_version']) is not int
            or certificate['schema_version'] != EXPLORATION_VERSION
            or certificate['kind'] != 'exploration_resources'
            or certificate['content_sha256'] != _digest(payload)
            or certificate['resources_sha256'] != _digest(resources)
            or _digest(certificate['scope']) != _digest(scope)):
        raise ValueError('exploration certificate resource, scope or digest mismatch')
    return deepcopy(certificate)


def _store_immutable(run: Path, relative: str, value: dict) -> Path:
    """Input: owning run Path, relative str, JSON dict. Output: immutable Path; reject corrupt or linked files."""
    root = Path(run).resolve(strict=True)
    path = _safe(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    with json_lock_transition_guard(path.parent / 'write_guard', 5.0, 0.05, 'exploration freeze busy'):
        path = _safe(root, relative)
        if path.exists():
            if _digest(json.loads(path.read_text(encoding='utf-8'))) != _digest(value):
                raise ValueError('immutable exploration evidence changed')
        else:
            _write(path, value)
    return path


def certify_exploration_resources(run: Path, knowledge_root: Path, resources: dict, scope: dict) -> dict:
    """Input: new run/vault Paths and resource/scope dicts. Output: immutable persisted certificate dict.

    Start must first persist run_manifest.json with selected_scope, knowledge_root
    and start_snapshot.selected_scope/research_policy. Policy requires paired_scout
    and exploration_scout exactly True, exploration_policy_version exactly 1.
    Call BEFORE dispatching any design model: this producer takes no model outcome.
    No raw capture, knowledge write, reviewed publication or research authority.
    """
    certificate = _resource_certificate(run, knowledge_root, resources, scope)
    relative = 'runtime/exploration/resources/' + certificate['content_sha256'] + '.json'
    _store_immutable(run, relative, certificate)
    return certificate


def validate_exploration_attachment(run: Path, knowledge_root: Path, receipt: dict, certificate: dict) -> dict:
    """Input: run/vault Paths, compiler receipt and pre-model certificate dicts. Output: verified receipt dict.

    Operational callers MUST invoke this IO boundary, not just snapshot validation.
    Recheck canonical registration, original extracts/repairs, bytes, owning policy
    and immutable stored certificate. This grants no live model/platform authority.
    """
    verified = verify_exploration(receipt)
    inputs = verified['compiler_input']
    bound = _verify_certificate(certificate, inputs['resources'], inputs['scope'])
    current = _resource_certificate(run, knowledge_root, inputs['resources'], inputs['scope'])
    if current != bound:
        raise ValueError('exploration resource certification is stale or belongs to another run')
    root = Path(run).resolve(strict=True)
    path = _safe(root, 'runtime/exploration/resources/' + bound['content_sha256'] + '.json')
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('missing or unreadable pre-model exploration certificate') from exc
    if _digest(saved) != _digest(bound):
        raise ValueError('persisted exploration resource certificate changed')
    return verified


def freeze_exploration(run: Path, receipt: dict, *, knowledge_root: Path | None = None,
                       certificate: dict | None = None) -> Path:
    """Input: run Path/receipt dict, vault Path/certificate dict. Output: IO-certified immutable receipt Path."""
    if knowledge_root is None or certificate is None:
        raise ValueError('operational freeze requires pre-model resource certificate and vault')
    verified = validate_exploration_attachment(run, knowledge_root, receipt, certificate)
    return _store_immutable(run, 'runtime/exploration/' + verified['content_sha256'] + '.json', verified)


def exploration_scout_enabled(policy: dict | None) -> bool:
    """Input: optional policy dict. Output: bool; reject coercion into new exploration authority."""
    if policy is None:
        return False
    if not isinstance(policy, dict) or type(policy.get('exploration_scout', False)) is not bool:
        raise ValueError('exploration_scout must be a bool')
    return policy.get('exploration_scout', False)


def build_exploration_snapshot(receipts: list[dict], *, resource_certificates: list[dict] | None = None) -> dict:
    """Input: compiler receipts/optional certificates lists. Output: pure selector-compatible snapshot dict.

    No reviewed release is created. Every consumed source and compilation stays
    attached for revalidation before candidate selection. Optional certificates
    are frozen context ONLY; validate_exploration_attachment remains mandatory
    at the operational boundary. Omitting them is useful for pure fixtures.
    """
    if not isinstance(receipts, list) or not receipts or len(receipts) > 30:
        raise ValueError('expected one to thirty exploration pairs')
    verified = [verify_exploration(row) for row in receipts]
    if len({row['content_sha256'] for row in verified}) != len(verified):
        raise ValueError('duplicate exploration receipts')
    scope = verified[0]['compiler_input']['scope']
    version = verified[0]['compiler_input']['resources'].get('resource_contract_version', 1)
    fields, operators, templates = [], [], []
    for row in verified:
        inputs = row['compiler_input']
        resources = inputs['resources']
        if inputs['scope'] != scope or resources.get('resource_contract_version', 1) != version:
            raise ValueError('exploration pairs must share scope and resource version')
        for target, source in ((fields, resources['field_rows']),
                               (operators, resources['operator_rows']),
                               (templates, row['compiled']['drafts'])):
            for item in source:
                if item not in target:
                    target.append(deepcopy(item))
    context = dict(schema_version=EXPLORATION_VERSION, receipts=verified)
    policy = dict(paired_scout=True, exploration_scout=True)
    if resource_certificates is not None:
        if not isinstance(resource_certificates, list) or len(resource_certificates) != len(verified):
            raise ValueError('one resource certificate required per exploration receipt')
        certificates = [_verify_certificate(cert, row['compiler_input']['resources'],
                        row['compiler_input']['scope']) for cert, row in zip(resource_certificates, verified)]
        if any(cert['owning_run'] != certificates[0]['owning_run'] or cert['policy'] != certificates[0]['policy']
               for cert in certificates):
            raise ValueError('exploration certificates must share owning run and frozen policy')
        context['resource_certificates'] = certificates
        policy = deepcopy(certificates[0]['policy'])
    return dict(resource_contract_version=version, hypothesis_binding_version=2,
                selected_scope=deepcopy(scope), template_rows=templates,
                data_ledger_rows=fields, operator_rows=operators,
                research_policy=policy,
                exploration_context=context)


def validate_exploration_snapshot(snapshot: dict) -> dict:
    """Input: frozen snapshot dict. Output: pure compiler selector context dict, never live IO authority."""
    if not exploration_scout_enabled(snapshot.get('research_policy')):
        raise ValueError('exploration context requires explicit policy')
    if 'semantic_release' in snapshot or 'operational_resource_context' in snapshot:
        raise ValueError('exploration cannot override a mixed reviewed-release context')
    if snapshot['research_policy'].get('paired_scout') is not True:
        raise ValueError('exploration requires complete paired experiments')
    context = snapshot.get('exploration_context')
    if (not isinstance(context, dict) or set(context) not in (
            {'schema_version', 'receipts'}, {'schema_version', 'receipts', 'resource_certificates'})
            or type(context['schema_version']) is not int
            or context['schema_version'] != EXPLORATION_VERSION):
        raise ValueError('invalid frozen exploration context')
    rebuilt = build_exploration_snapshot(context['receipts'],
        resource_certificates=context.get('resource_certificates'))
    if ('resource_certificates' in context
            and _digest(snapshot['research_policy']) != _digest(rebuilt['research_policy'])):
        raise ValueError('exploration snapshot differs from certified frozen policy')
    for key in ('resource_contract_version', 'hypothesis_binding_version', 'selected_scope',
                'template_rows', 'data_ledger_rows', 'operator_rows', 'exploration_context'):
        if _digest(snapshot.get(key)) != _digest(rebuilt[key]):
            raise ValueError('exploration snapshot differs from verified ' + key)
    index, texts, experiments = {}, {}, []
    for receipt in rebuilt['exploration_context']['receipts']:
        resources = receipt['compiler_input']['resources']
        for path, source in resources['source_index'].items():
            text = resources['source_texts'][path]
            if path in index and (index[path] != source or texts[path] != text):
                raise ValueError('exploration source conflicts across pairs')
            index[path], texts[path] = source, text
        experiments.append(receipt['compiled']['experiment'])
    return dict(resource_contract_version=rebuilt['resource_contract_version'],
                source_index=index, source_texts=texts, experiments=experiments,
                exploration_template_ids=[row['template_id'] for row in rebuilt['template_rows']])


def validate_operational_exploration(run: Path, knowledge_root: Path, snapshot: dict) -> dict:
    """Input: owning run/vault Paths and snapshot dict. Output: IO-verified frozen compiler context.

    Pure selector fixtures cannot authorize source execution. Recheck pre-model
    certificates, original raw bytes and owning policy at the planning boundary.
    """
    context = validate_exploration_snapshot(snapshot)
    frozen = snapshot['exploration_context']
    certificates = frozen.get('resource_certificates')
    if not isinstance(certificates, list) or len(certificates) != len(frozen['receipts']):
        raise ValueError('operational exploration requires pre-model resource certificates')
    for receipt, certificate in zip(frozen['receipts'], certificates):
        validate_exploration_attachment(run, knowledge_root, receipt, certificate)
    return context
