"""Script-owned sealing of existing selected inputs; never model or live authority."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from wqb.semantic_compilation import _safe


PACKAGE_VERSION = 1
SEAL_PATH = 'runtime/execution_package/seal.json'
TREE_PATH = 'runtime/experiment_tree.json'
MAX_LOCAL_INPUT_BYTES = 256_000_000
MAX_CERTIFICATES = 30
SEAL_KEYS = {'schema_version', 'kind', 'run_id', 'manifest_sha256', 'tree_sha256',
             'snapshot_sha256', 'context_sha256', 'certificate_refs', 'data_characteristics', 'content_sha256'}


def _digest(value: object) -> str:
    """Input: finite JSON value. Output: canonical SHA256 string; no permission grant."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode('utf-8')).hexdigest()


def _root(run: Path) -> Path:
    """Input: owning run Path. Output: checked absolute local Path; never resolve the knowledge root."""
    run = Path(run).absolute()
    if any(path.is_symlink() or path.is_junction() for path in (run, *run.parents)):
        raise ValueError('execution package cannot traverse links')
    return run.resolve(strict=True)


def _read(run: Path, relative: str) -> tuple[dict, str]:
    """Input: checked run/relative path. Output: object and exact byte hash; bound local reads."""
    path = _safe(run, relative)
    if path.stat().st_size > MAX_LOCAL_INPUT_BYTES:
        raise ValueError('execution package input exceeds byte bound')
    raw = path.read_bytes()
    if len(raw) > MAX_LOCAL_INPUT_BYTES:
        raise ValueError('execution package input grew beyond byte bound')
    value = json.loads(raw)
    if type(value) is not dict:
        raise ValueError('execution package object required')
    return value, hashlib.sha256(raw).hexdigest()


def package_enabled(snapshot: dict) -> bool:
    """Input: frozen Start snapshot dict. Output: bool; only exact versioned producer opt-in enables local reads."""
    if not isinstance(snapshot, dict):
        raise ValueError('execution package requires a snapshot object')
    policy = snapshot.get('research_policy', {})
    if not isinstance(policy, dict):
        raise ValueError('invalid execution package policy')
    if 'execution_package_version' not in policy:
        return False
    version = policy['execution_package_version']
    tree_version = policy.get('preplanned_tree_version')
    if (type(version) is not int or version != PACKAGE_VERSION
            or type(tree_version) is not int or tree_version != 1):
        raise ValueError('unsupported execution package policy version')
    return True


def _certificates(run: Path, manifest: dict) -> list[dict]:
    """Input: checked run and frozen manifest. Output: unique exact local certificate references, not global source IO."""
    from wqb.exploration_eligibility import _digest as certificate_digest

    snapshot = manifest['start_snapshot']
    certificates = snapshot['exploration_context']['resource_certificates']
    if not 1 <= len(certificates) <= MAX_CERTIFICATES:
        raise ValueError('invalid execution package certificate count')
    policy = snapshot['research_policy']
    context = dict(run_id=run.name, knowledge_root=manifest['knowledge_root'],
        selected_scope=manifest['selected_scope'], created_at=manifest.get('created_at'),
        selected_option_id=manifest.get('selected_option_id'), research_policy=policy)
    references = {}
    for certificate in certificates:
        owner = certificate['owning_run']
        if (owner.get('run_id') != run.name
                or os.path.normcase(os.path.normpath(owner.get('path', ''))) != os.path.normcase(str(run))
                or owner.get('knowledge_root') != manifest['knowledge_root']
                or owner.get('start_context_sha256') != certificate_digest(context)
                or certificate['policy'] != policy
                or certificate['scope'] != manifest['selected_scope']):
            raise ValueError('execution package source certificate owner differs')
        digest = certificate['content_sha256']
        if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('invalid execution package certificate identity')
        path = 'runtime/exploration/resources/' + digest + '.json'
        saved, byte_hash = _read(run, path)
        if saved != certificate:
            raise ValueError('execution package certificate changed')
        references[path] = dict(path=path, sha256=byte_hash)
    return [references[path] for path in sorted(references)]


def _annotations(run: Path, manifest: dict) -> dict:
    """Input: owner Path/frozen manifest dict. Output: checked script artifact path/hash from local facts only."""
    from wqb.initial_research_planning import (
        DATA_CHARACTERISTICS_PATH, _annotation_context, _annotation_fields,
    )
    try:
        artifact, byte_hash = _read(run, DATA_CHARACTERISTICS_PATH)
    except OSError as error:
        raise ValueError('execution package requires script-resolved annotations') from error
    snapshot = manifest['start_snapshot']
    frozen = snapshot['exploration_context']
    keys = {'schema_version', 'input_sha256', 'resource_certificate_sha256',
            'repair_search_policy_sha256', 'purpose', 'fields'}
    if (set(artifact) != keys or type(artifact['schema_version']) is not int
            or artifact['schema_version'] != 1 or artifact['purpose'] != 'documentation_only'
            or artifact['repair_search_policy_sha256'] != _digest(snapshot['repair_search_policy'])
            or artifact['resource_certificate_sha256'] not in
                {row['content_sha256'] for row in frozen['resource_certificates']}):
        raise ValueError('execution package annotations differ from frozen resources')
    identity = artifact['input_sha256']
    if type(identity) is not str or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
        raise ValueError('invalid annotation input identity')
    fields, used, context = {}, set(), None
    for receipt in frozen['receipts']:
        current = _annotation_context(receipt['compiler_input']['resources'], manifest)
        context = current
        for row in current['fields']:
            key = (row['dataset_id'], row['field_id'])
            if key in fields and fields[key] != row:
                raise ValueError('conflicting execution annotation facts')
            fields[key] = row
        experiment = receipt['compiled']['experiment']
        bindings = list(experiment['context_bindings'].values())
        bindings.extend(binding for arm in experiment['arms'] for binding in arm['binding']['bindings'].values())
        used.update((row['dataset_id'], row['field_id']) for row in bindings)
    context['fields'] = list(fields.values())
    proposed = [dict(dataset_id=row['dataset_id'], field_id=row['field_id'],
        known_trait_keys=row['referenced_trait_keys'], unknown_trait_keys=row['unknown_trait_keys'],
        hypotheses=row['hypotheses'], suggested_repair_rule_ids=row['suggested_repair_rule_ids'])
        for row in artifact['fields']]
    expected = _annotation_fields(dict(data_characteristics=proposed), dict(annotation_context=context), used)
    if expected != artifact['fields']:
        raise ValueError('execution package annotation facts changed')
    return dict(path=DATA_CHARACTERISTICS_PATH, sha256=byte_hash)


def seal_execution_context(run: Path) -> dict:
    """Input: source-certified new tree run. Output: immutable script-generated seal of existing local inputs.

    The one producer still executes the existing raw/certificate/compiler checks.
    No vault copy or model-supplied package is accepted. A repeated successful
    freeze reuses the same local bytes, not a new global certification.
    """
    from wqb.exploration_eligibility import _store_immutable, validate_exploration_snapshot
    from wqb.research_tree import _authenticate, _authenticated_attachment

    run = _root(run)
    manifest, manifest_hash = _read(run, 'run_manifest.json')
    if manifest.get('run_id') != run.name or not package_enabled(manifest['start_snapshot']):
        raise ValueError('execution package requires owning versioned frozen Start')
    if _safe(run, SEAL_PATH).exists():
        return load_execution_package(run)['seal']
    tree, tree_hash = _read(run, TREE_PATH)
    validated, snapshot, authenticated_hash = _authenticate(run, tree['proposed_tree'], tree['resources'],
                                                          certify_sources=True)
    expected = _authenticated_attachment(run, tree['proposed_tree'], tree['resources'],
                                         validated, snapshot, authenticated_hash)
    if authenticated_hash != manifest_hash or tree != expected:
        raise ValueError('execution package tree differs from certified owner')
    context = validate_exploration_snapshot(snapshot)
    seal = dict(schema_version=PACKAGE_VERSION, kind='script_execution_package', run_id=run.name,
        manifest_sha256=manifest_hash, tree_sha256=tree_hash,
        snapshot_sha256=_digest(snapshot), context_sha256=_digest(context),
        certificate_refs=_certificates(run, manifest), data_characteristics=_annotations(run, manifest))
    seal['content_sha256'] = _digest(seal)
    if _read(run, 'run_manifest.json')[1] != manifest_hash or _read(run, TREE_PATH)[1] != tree_hash:
        raise ValueError('execution package inputs changed during freeze')
    _store_immutable(run, SEAL_PATH, seal)
    return deepcopy(seal)


def load_execution_package(run: Path) -> dict:
    """Input: sealed owning run. Output: validated local seal/snapshot/context/attachment; no global catalog reads."""
    from wqb.exploration_eligibility import validate_exploration_snapshot

    run = _root(run)
    from wqb.execution_package_lifecycle import RETIRED_RECEIPT, load_retired_summary
    if _safe(run, RETIRED_RECEIPT).exists():
        load_retired_summary(run)
        raise ValueError('completed execution package is retired and read-only')
    try:
        manifest, manifest_hash = _read(run, 'run_manifest.json')
        snapshot = manifest['start_snapshot']
        if manifest.get('run_id') != run.name or not package_enabled(snapshot):
            raise ValueError('execution package owner or policy differs')
        seal, _ = _read(run, SEAL_PATH)
        if (set(seal) != SEAL_KEYS or type(seal['schema_version']) is not int
                or seal['schema_version'] != PACKAGE_VERSION or seal['run_id'] != run.name
                or seal['kind'] != 'script_execution_package'
                or seal['content_sha256'] != _digest({k: v for k, v in seal.items() if k != 'content_sha256'})
                or seal['manifest_sha256'] != manifest_hash or seal['snapshot_sha256'] != _digest(snapshot)):
            raise ValueError('execution package seal or owning Start changed')
        attachment, tree_hash = _read(run, TREE_PATH)
        if tree_hash != seal['tree_sha256'] or attachment.get('manifest_sha256') != manifest_hash:
            raise ValueError('execution package tree attachment changed')
        if _certificates(run, manifest) != seal['certificate_refs']:
            raise ValueError('execution package certificate references changed')
        if _annotations(run, manifest) != seal['data_characteristics']:
            raise ValueError('execution package annotation reference changed')
        context = validate_exploration_snapshot(snapshot)
        if _digest(context) != seal['context_sha256']:
            raise ValueError('execution package compiled context changed')
        return dict(seal=seal, manifest=manifest, snapshot=deepcopy(snapshot), context=context, attachment=attachment)
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError('execution package missing or invalid local input') from error


def load_execution_context(run: Path, expected_snapshot: dict | None = None) -> dict:
    """Input: owning run/optional expected snapshot. Output: verified context; caller-supplied snapshots never override local authority."""
    package = load_execution_package(run)
    if expected_snapshot is not None and expected_snapshot != package['snapshot']:
        raise ValueError('execution package snapshot differs from owning Start')
    return package['context']
