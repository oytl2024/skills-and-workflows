"""K4 local inventory and immutable preparation, deliberately without an executor.

The returned plan is root-bound. Inventory is JSONL, one row per meaning identity;
occurrences retain exact scopes and original rows, never a Cartesian scope union.
Job manifests bind complete bounded input and brief bytes. A cached job means only
unchanged prepared input, not a successful, reviewed or replayable model result.
Certified extracts share invocation-local original/index scans, retaining exact
per-extract proofs and final digest revalidation before preparation writes.
"""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re

from wqb.knowledge_contracts import (
    MAX_FIELD_CAPTURE_LINE_BYTES, _capture_json_object, _write_immutable_source,
    parse_markdown_front_matter, verify_field_source_extracts, extract_field_source_batches,
    DEFAULT_FIELD_EXTRACT_BATCHES, DEFAULT_FIELD_EXTRACT_FIELDS,
    MAX_BULK_FIELD_BATCHES, MAX_BULK_FIELD_FIELDS,
)
from wqb.knowledge_paths import LEGACY_MACHINE_RESOURCE_PATHS, machine_resource_path
from wqb.semantic_compilation import (
    MAX_MATERIAL_BYTES, MAX_OUTPUT_BYTES, MAX_PACK_BYTES, MAX_SELECTED_SOURCES,
    MAX_SOURCE_BYTES, _digest, _hash, _material, _safe,
)


SCHEMA_VERSION = 1
PREPARE_VERSION = 'full-local-semantic-prepare-1'
DEFAULT_TARGETS_PER_JOB = 24
DEFAULT_OUTPUT_TOKENS_PER_TARGET = 500
DEFAULT_MAX_RUNTIME_SECONDS = 3600
SCOPE_KEYS = ('instrument_type', 'region', 'delay', 'universe')
INVENTORY_GAP_CODES = {'line_bound', 'invalid_row', 'invalid_source_record', 'invalid_encoding',
                       'unsafe_path', 'invalid_index', 'active_release_gap', 'inventory_source_gap'}
OUTPUT_CONTRACT = dict(
    required_target_fields=['target_id', 'identity', 'literal_fact_summary', 'typed_facts',
                            'hypothesis_cards', 'conditional_uses', 'missing_facts',
                            'conflicting_facts', 'evidence_refs'],
    exact_once=True, reject_extra_ids=True, reject_omissions=True,
    reject_unsupported_formulas=True, facts_require_source_evidence=True,
    unresolved_semantics_allowed=True, literal_fact_summary_nullable=True,
    allowed_semantic_statuses=['explained', 'partial', 'unresolved', 'conflicting', 'unsupported'],
    missing_semantics_rule='Use null summary and empty typed facts when unsupported; record missing_facts, never invent descriptions',
    economic_explanations_default='hypothesis', publication_authorized=False,
)
BRIEF = ('Explain every exact target once. Preserve literal field-specific meanings and exact scopes. '
         'Use sourced typed facts only; mark unsupported timing, units, grain and polarity unknown. '
         'Label economic mechanisms and conditional uses as hypotheses unless measured evidence is bound. '
         'Retain conflicts and missing facts. Missing or unresolved semantics are valid outputs; '
         'use a null literal_fact_summary and empty typed_facts rather than inventing a description. '
         'Byte validation does not establish freshness, compiler eligibility or research readiness. '
         'Do not invent formula operators or publish resources.')


def _bytes(value: object) -> bytes:
    """Input: JSON-compatible object. Output: canonical UTF-8 bytes for immutable hashing."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _json(text: str):
    """Input: JSON str. Output: parsed object/list; reject ambiguous duplicate keys and NaN."""
    def invalid(value):
        """Input: nonfinite token str. Output: exception; prohibit noncanonical numeric facts."""
        raise ValueError('nonfinite JSON constant: ' + value)
    return json.loads(text, object_pairs_hook=_capture_json_object, parse_constant=invalid)


def _rows(path: Path, diagnostics: list):
    """Input: safe JSONL Path/diagnostics list. Output: object iterator, bounded per line."""
    if not path.exists():
        return
    try:
        stream = path.open('rb')
    except OSError as exc:
        diagnostics.append(dict(path=path.as_posix(), code='inventory_source_gap', message=str(exc)))
        return
    with stream:
        number = 0
        while True:
            line = stream.readline(MAX_FIELD_CAPTURE_LINE_BYTES + 1)
            if not line:
                break
            number += 1
            if len(line) > MAX_FIELD_CAPTURE_LINE_BYTES:
                diagnostics.append(dict(path=path.name, line=number, code='line_bound',
                                        message='Oversized record not parsed; inventory incomplete'))
                # Drain this record without interpreting a truncated payload as a new row.
                while line and not line.endswith(b'\n'):
                    line = stream.readline(MAX_FIELD_CAPTURE_LINE_BYTES + 1)
                continue
            if not line.strip():
                continue
            try:
                row = _json(line.decode('utf-8'))
                if not isinstance(row, dict):
                    raise ValueError('expected object row')
                yield row
            except (ValueError, UnicodeError) as exc:
                diagnostics.append(dict(path=path.name, line=number, code='invalid_row', message=str(exc)))


def _raw_paths(root: Path, diagnostics: list):
    """Input: vault Path/diagnostics list. Output: safe relevant raw file iterator; never follow links."""
    base = _safe(root, 'raw/platform')
    if not base.exists():
        return
    for parent, dirs, files in os.walk(base, followlinks=False):
        allowed = []
        for name in sorted(dirs):
            relative = (Path(parent) / name).relative_to(root).as_posix()
            try:
                _safe(root, relative, source=True)
                allowed.append(name)
            except ValueError:
                diagnostics.append(dict(path=relative, code='unsafe_path', message='Skipped unsafe raw directory'))
        dirs[:] = allowed
        for name in sorted(files):
            if (name in {'data_fields.jsonl', 'operators.json', 'operators.jsonl', 'operators.md'}
                    or name.startswith('semantic-subset-') and name.endswith('.jsonl')):
                yield (Path(parent) / name).relative_to(root).as_posix()


def _objects(value):
    """Input: structured JSON object/list. Output: resource dict iterator without guessed prose facts."""
    if isinstance(value, list):
        for item in value:
            yield from _objects(item)
    elif isinstance(value, dict):
        if 'field' in value or 'field_id' in value or 'operator' in value:
            yield value
        elif 'dataset' in value and 'id' in value or 'name' in value or 'id' in value and 'definition' in value:
            yield value
        else:
            for key in ('operators', 'results', 'data', 'fields', 'rows'):
                if key in value:
                    yield from _objects(value[key])


def _operator_source(relative: str, source: dict | None = None) -> bool:
    """Input: raw path str/optional index dict. Output: bool; recognize operator catalogs, not substrings."""
    return (relative.startswith('raw/platform/')
            and (Path(relative).name in {'operators.md', 'operators.json', 'operators.jsonl'}
                 or (source or {}).get('source_family') == 'raw/platform/operators'))


def _parse(text: str, relative: str, diagnostics: list, source: dict | None = None):
    """Input: full source text/path/diagnostics. Output: (row, complete material) iterator; one parse."""
    if relative.endswith('.md'):
        _, body = parse_markdown_front_matter(text.replace('\r\n', '\n'))
        matches = list(re.finditer(r'^###\s+`?([A-Za-z_][A-Za-z0-9_.-]*)`?\s*$', body, re.MULTILINE))
        explicit = (source or {}).get('target_ids', [])
        if matches and (_operator_source(relative, source) or explicit):
            names = Counter(match[1] for match in matches)
            for i, match in enumerate(matches):
                if explicit and match[1] not in explicit:
                    continue
                section = body[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(body)]
                category = re.search(r'^##\s+', section, re.MULTILINE)
                if category:
                    section = section[:category.start()]
                yield dict(operator=match[1], literal_source=section,
                           ambiguous=names[match[1]] > 1), section
            return
        # Only complete JSON blocks are interpreted; surrounding prose stays unasserted.
        candidates = re.findall(r'```json\s*\n(.*?)\n```', body, re.DOTALL)
    elif relative.endswith('.jsonl'):
        candidates = text.splitlines()
    else:
        candidates = [text]
    for candidate in candidates:
        if not candidate.strip():
            continue
        try:
            value = _json(candidate)
            for row in _objects(value):
                yield row, _bytes(row).decode('utf-8')
        except ValueError as exc:
            diagnostics.append(dict(path=relative, code='invalid_source_record', message=str(exc)))


def _scope_rows(row: dict) -> list:
    """Input: raw/canonical row dict. Output: exact scope objects, never a cross-product."""
    if isinstance(row.get('scope'), dict):
        return [row['scope']]
    if isinstance(row.get('available_scopes'), list) and row['available_scopes']:
        return [scope for scope in row['available_scopes'] if isinstance(scope, dict)]
    scope = {key: row[key] for key in SCOPE_KEYS if key in row}
    return [scope] if scope else []


def _identity(row: dict, operator_source: bool = False):
    """Input: resource row dict/operator-source bool. Output: kind/identity or None for nonresources."""
    field = row.get('field', row)
    dataset = row.get('data_set', row.get('dataset', {}))
    if isinstance(field, dict):
        dataset_id = row.get('dataset_id') or (dataset.get('id') if isinstance(dataset, dict) else dataset)
        field_id = field.get('field_id', field.get('id'))
        if isinstance(dataset_id, str) and dataset_id and isinstance(field_id, str) and field_id:
            return 'field', dict(dataset_id=dataset_id, field_id=field_id)
    name = row.get('operator') or (row.get('name', row.get('id')) if operator_source else None)
    if isinstance(name, str) and name:
        return 'operator', dict(operator=name)
    return None


def _source_refs(row: dict) -> list:
    """Input: canonical resource dict. Output: original source paths without inventing certification."""
    paths = set(item for item in row.get('source_paths', []) if isinstance(item, str)) if isinstance(row.get('source_paths', []), list) else set()
    refs = list(row.get('evidence_refs', [])) if isinstance(row.get('evidence_refs', []), list) else []
    definition = row.get('definition')
    if isinstance(definition, dict):
        if isinstance(definition.get('evidence_refs', []), list):
            refs.extend(definition.get('evidence_refs', []))
    paths.update(ref['source_path'] for ref in refs if isinstance(ref, dict) and isinstance(ref.get('source_path'), str))
    return sorted(paths)


def _add(targets: dict, row: dict, path: str, origin: str, verified: bool,
         material: str = '', source: dict | None = None) -> None:
    """Input: target map/resource/provenance/material. Output: None; accumulate lossless distinct occurrences."""
    identity = _identity(row, _operator_source(path, source))
    if identity is None:
        return
    kind, value = identity
    key = kind + ':' + _digest(value)
    target = targets.setdefault(key, dict(target_id=key, kind=kind, identity=value,
        occurrences={}, scopes={}, source_refs={}, materials={}))
    scopes = _scope_rows(row)
    for scope in scopes:
        target['scopes'][_digest(scope)] = scope
    refs = [path] if origin == 'raw' else _source_refs(row)
    for ref in refs:
        target['source_refs'][ref] = dict(source) if source and ref == path else dict(path=ref)
    occurrence = dict(origin=origin, path=path, row=row, scopes=scopes, source_refs=refs,
                      source_validated=verified and not row.get('ambiguous', False))
    occurrence_key = _digest(occurrence)
    if occurrence_key in target['occurrences']:
        target['occurrences'][occurrence_key]['count'] += 1
    else:
        target['occurrences'][occurrence_key] = dict(occurrence, count=1)
    if occurrence['source_validated'] and material:
        item = dict(target_id=key, source_index=source, scopes=scopes, content=material,
                    sha256=_hash(material.encode('utf-8')))
        target['materials'][_digest(item)] = item


def _presence_material(path: Path, relative: str, diagnostics: list, targets: dict) -> tuple:
    """Input: safe Path/raw path/diagnostics/targets. Output: text/hash tuple; bounded, unverified presence only."""
    digest = hashlib.sha256()
    try:
        if path.stat().st_size <= MAX_SOURCE_BYTES:
            raw = path.read_bytes()
            return raw.decode('utf-8'), _hash(raw)
        if not relative.endswith('.jsonl'):
            diagnostics.append(dict(path=relative, code='inventory_source_gap',
                                    message='Oversized source omitted; identities not inventoried'))
            return None, 'unread_oversize'
        # Large JSONL remains streamable for presence without granting source trust.
        with path.open('rb') as stream:
            while True:
                raw = stream.readline(MAX_FIELD_CAPTURE_LINE_BYTES + 1)
                if not raw:
                    break
                digest.update(raw)
                if len(raw) > MAX_FIELD_CAPTURE_LINE_BYTES:
                    diagnostics.append(dict(path=relative, code='line_bound', message='Record exceeds inventory parse bound'))
                    while raw and not raw.endswith(b'\n'):
                        raw = stream.readline(MAX_FIELD_CAPTURE_LINE_BYTES + 1)
                        digest.update(raw)
                    continue
                if not raw.strip():
                    continue
                try:
                    row = _json(raw.decode('utf-8'))
                    if not isinstance(row, dict):
                        raise ValueError('expected object row')
                    _add(targets, row, relative, 'raw', False)
                except (ValueError, UnicodeError) as exc:
                    diagnostics.append(dict(path=relative, code='invalid_source_record', message=str(exc)))
        return None, digest.hexdigest()
    except (OSError, UnicodeError) as exc:
        diagnostics.append(dict(path=relative, code='inventory_source_gap', message=str(exc)))
        return None, 'unreadable'


def _freeze(root: Path, relative: str, raw: bytes) -> dict:
    """Input: vault Path/relative str/complete bytes. Output: immutable path/hash reference."""
    path = _safe(root, relative)
    _write_immutable_source(path, raw)
    return dict(path=relative, sha256=_hash(raw))


def _contracts(config: dict) -> dict:
    """Input: config dict. Output: source/rule/schema-bound contracts; no increased material bounds."""
    code = Path(__file__).parent
    owners = ('semantic_compilation.py', 'semantic_contracts.py', 'resource_evidence.py',
              'knowledge_contracts.py', 'operator_semantics.py', 'data_ledger.py', 'full_semantic_compile.py')
    return dict(schema_version=SCHEMA_VERSION, prepare_version=PREPARE_VERSION,
                rules_version=config.get('rules_version', ''),
                code_digests={name: _hash((code / name).read_bytes()) for name in owners},
                output_contract_sha256=_digest(OUTPUT_CONTRACT), brief_sha256=_hash(BRIEF.encode()),
                bounds=dict(max_material_bytes=MAX_MATERIAL_BYTES, max_pack_bytes=MAX_PACK_BYTES,
                            max_source_bytes=MAX_SOURCE_BYTES, max_output_bytes=MAX_OUTPUT_BYTES,
                            max_targets_per_job=config['max_targets_per_job'],
                            max_sources=MAX_SELECTED_SOURCES))


def _jobs(root: Path, targets: list, materials: dict, contracts: dict, config: dict) -> tuple:
    """Input: inventory/materials/contracts/config. Output: immutable job refs and cached job count."""
    groups = {}
    for target in targets:
        if target['status'] == 'blocked':
            continue
        group = target['kind'] + ':' + str(target['identity'].get('dataset_id', 'operators'))
        groups.setdefault(group, []).append(target)
    jobs, cached = [], 0

    def pack(batch, group):
        """Input: target list/group str. Output: complete bounded worker input dict."""
        ids = [target['target_id'] for target in batch]
        return dict(schema_version=SCHEMA_VERSION, root=str(root), group=group,
                    targets=[dict(target_id=t['target_id'], kind=t['kind'], identity=t['identity'],
                                  scopes=t['scopes'], source_refs=t['source_refs'],
                                  source_validated_scopes=t['source_validated_scopes'], gaps=t['gaps']) for t in batch],
                    materials=[item for target_id in ids for item in materials[target_id]],
                    output_contract=dict(OUTPUT_CONTRACT, exact_target_ids=ids), contracts=contracts)

    def fits(batch, group):
        """Input: tentative batch/group. Output: bool; apply existing independent material/pack/source limits."""
        value = pack(batch, group)
        return (len(batch) <= config['max_targets_per_job']
                and sum(len(item['content'].encode('utf-8')) for item in value['materials']) <= MAX_MATERIAL_BYTES
                and len({item['source_index']['path'] for item in value['materials']}) <= MAX_SELECTED_SOURCES
                and len(_bytes(value)) <= MAX_PACK_BYTES)

    def save(batch, group):
        """Input: finite target batch/group. Output: None; freeze input/brief/manifest and attach target IDs."""
        nonlocal cached
        if not batch:
            return
        value = pack(batch, group)
        raw = _bytes(value)
        key = _digest(dict(input_sha256=_hash(raw), contracts=contracts, root=str(root)))
        base = 'machine/semantic_jobs/' + key
        existing = _safe(root, base + '/run_manifest.json').exists()
        input_ref = _freeze(root, base + '/input.json', raw)
        brief_ref = _freeze(root, base + '/brief.txt', BRIEF.encode())
        ids = [t['target_id'] for t in batch]
        manifest = dict(kind='full_semantic_explanation', schema_version=SCHEMA_VERSION,
                        root=str(root), content_key=key, contracts=contracts, target_ids=ids,
                        targets=value['targets'], group=group, materials=value['materials'],
                        input_ref=input_ref, brief_ref=brief_ref, input_bytes=len(raw),
                        output_contract=value['output_contract'], gaps=[], model_calls=0)
        ref = _freeze(root, base + '/run_manifest.json', _bytes(manifest))
        jobs.append(dict(job_id=key, **ref, target_ids=ids, group=group,
                         input_sha256=input_ref['sha256'], brief_sha256=brief_ref['sha256'],
                         input_bytes=len(raw), estimated_input_tokens=(len(raw) + 3) // 4,
                         estimated_output_tokens=len(batch) * config['output_tokens_per_target']))
        cached += int(existing)
        for target in batch:
            target.update(status='prepared', job_id=key)

    for group, candidates in sorted(groups.items()):
        batch = []
        for target in candidates:
            if not fits([target], group):
                target['status'] = 'blocked'
                target['gaps'].append(dict(code='material_bound', message='Complete target material exceeds bounded input; no truncation'))
                continue
            if batch and not fits(batch + [target], group):
                save(batch, group)
                batch = []
            batch.append(target)
        save(batch, group)
    return jobs, cached


def prepare_full_semantic_compile(root: Path, config: dict) -> dict:
    """Input: vault Path/config dict. Output: deterministic root-bound plan and immutable job references.

    Config: model_call_budget=0, max_runtime_seconds=3600, max_targets_per_job=24
    (1..24), output_tokens_per_target=500, optional rules_version string. No model,
    publication, raw repair, result replay or runtime authority is implemented.
    Presence and source validation are not compiler/binder eligibility. Invalid
    sources are diagnosed independently and their identifiable targets retained.
    """
    if not isinstance(config, dict):
        raise ValueError('prepare config must be an object')
    config = dict(config)
    defaults = dict(model_call_budget=0, max_runtime_seconds=DEFAULT_MAX_RUNTIME_SECONDS,
                    max_targets_per_job=DEFAULT_TARGETS_PER_JOB,
                    output_tokens_per_target=DEFAULT_OUTPUT_TOKENS_PER_TARGET)
    for key, default in defaults.items():
        value = config.setdefault(key, default)
        if type(value) is not int or value < (0 if key == 'model_call_budget' else 1):
            raise ValueError(key + ' must be a finite integer within bounds')
    if config['max_targets_per_job'] > DEFAULT_TARGETS_PER_JOB:
        raise ValueError('target batch limit cannot exceed existing bounded default')
    if not isinstance(config.get('rules_version', ''), str):
        raise ValueError('rules_version must be a string')
    local_extracts = config.get('local_field_extracts')
    if local_extracts is not None:
        if (not isinstance(local_extracts, dict) or 'source_paths' not in local_extracts
                or set(local_extracts) - {'source_paths', 'max_batches', 'max_fields', 'identities_by_source'}
                or not isinstance(local_extracts['source_paths'], list)
                or any(not isinstance(p, str) for p in local_extracts['source_paths'])):
            raise ValueError('local_field_extracts requires explicit source_paths and finite bounds')
        local_extracts = dict(local_extracts)
        for name, default, limit in (('max_batches', DEFAULT_FIELD_EXTRACT_BATCHES, MAX_BULK_FIELD_BATCHES),
                                      ('max_fields', DEFAULT_FIELD_EXTRACT_FIELDS, MAX_BULK_FIELD_FIELDS)):
            value = local_extracts.setdefault(name, default)
            if type(value) is not int or not 1 <= value <= limit:
                raise ValueError(name + ' must be a finite positive integer <= ' + str(limit))
    root = Path(root).absolute()
    # Check root ancestors before resolving so a symlink/junction cannot disappear.
    for parent in (root, *root.parents):
        if parent.is_symlink() or hasattr(parent, 'is_junction') and parent.is_junction():
            raise ValueError('symlink/junction vault denied')
    root = root.resolve(strict=True)
    _safe(root, 'machine/semantic_jobs')
    diagnostics, indexed, conflicts, targets, dependencies = [], {}, set(), {}, {}
    captured_targets, large_originals = {}, {}

    def captured_presence(relative, row):
        """Input: original path str/captured row dict. Output: None; preserve unverified inventory occurrences."""
        if relative not in large_originals:
            large_originals[relative] = (root / relative).stat().st_size > MAX_SOURCE_BYTES
        if large_originals[relative]:
            _add(captured_targets.setdefault(relative, {}), row, relative, 'raw', False)

    preparation = None
    extra_session = None
    if local_extracts is not None:
        preparation = extract_field_source_batches(root, **local_extracts,
            _on_row=captured_presence, _defer_finalize=True)
        session = preparation.pop('_verification_session')
    index_path = _safe(root, 'machine/source_index.jsonl')
    for row in _rows(index_path, diagnostics):
        path = row.get('path')
        if not isinstance(path, str):
            diagnostics.append(dict(path='machine/source_index.jsonl', code='invalid_index',
                                    row_sha256=_digest(row), message='Source path missing'))
            continue
        if path in indexed and row != indexed[path]:
            conflicts.add(path)
        indexed[path] = row
    paths = set(indexed)
    paths.update(_raw_paths(root, diagnostics))
    extract_paths = [path for path, row in indexed.items()
                     if row.get('content_status') == 'verified_raw_extract'
                     or path.startswith('raw/platform/data_fields/') and Path(path).name.startswith('semantic-subset-')]
    if preparation is None:
        session = verify_field_source_extracts(root, extract_paths, _on_row=captured_presence)
    else:
        extra_paths = sorted(set(extract_paths) - set(session.paths()))
        if extra_paths:
            # Unselected existing extracts keep their ordinary independent proof;
            # never claim the finite new preparation verified other identities.
            extra_session = verify_field_source_extracts(root, extra_paths, _on_row=captured_presence)
    for relative, source_targets in captured_targets.items():
        if (session.original(relative) is not None
                or extra_session is not None and extra_session.original(relative) is not None):
            for target in source_targets.values():
                for occurrence in target['occurrences'].values():
                    for _ in range(occurrence['count']):
                        _add(targets, occurrence['row'], relative, 'raw', False)
    del captured_targets
    for relative in sorted(paths):
        source = indexed.get(relative)
        verified, text, safe, before, source_gap = False, None, None, None, None
        active_session = (extra_session if extra_session is not None
                          and (relative in extra_paths or extra_session.original(relative) is not None) else session)
        try:
            safe = _safe(root, relative, source=True)
            before = safe.stat()
            if relative in conflicts:
                raise ValueError('conflicting source registrations')
            if source is None:
                raise ValueError('unindexed raw presence only')
            normalized, text = _material(root, source, _verification_session=active_session)
            if source.get('file_sha256', normalized['file_sha256']) != normalized['file_sha256']:
                raise ValueError('asserted full-file hash mismatch')
            source, verified = normalized, True
        except (OSError, ValueError, TypeError) as exc:
            source_gap = dict(path=relative, code='source_gap', message=str(exc))
            diagnostics.append(source_gap)
        # Unsafe paths are never opened, even for presence-only diagnostics.
        if safe is None or before is None or not safe.is_file():
            if source_gap is None:
                source_gap = dict(path=relative, code='source_gap', message='Source disappeared before inventory')
                diagnostics.append(source_gap)
            source_gap['inventory_unresolved'] = True
            for target_id in (source or {}).get('target_ids', []):
                _add(targets, dict(operator=target_id), relative, 'index', False)
            dependencies[relative] = dict(source=source, status='unreadable')
            continue
        actual_hash = _hash(text.encode('utf-8')) if text is not None else None
        if verified:
            actual_hash = source['file_sha256']
        if text is None:
            captured = active_session.original(relative)
            if captured is not None and before.st_size > MAX_SOURCE_BYTES:
                actual_hash = captured['original_sha256']
            else:
                text, actual_hash = _presence_material(safe, relative, diagnostics, targets)
        if text is not None:
            for row, material in _parse(text, relative, diagnostics, source):
                _add(targets, row, relative, 'raw', verified, material, source)
        after = safe.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError('source mutated during inventory: ' + relative)
        dependencies[relative] = dict(source=source, actual_sha256=actual_hash,
                                      source_validated=verified)
        for target_id in (source or {}).get('target_ids', []):
            if 'operator:' + _digest(dict(operator=target_id)) not in targets:
                _add(targets, dict(operator=target_id), relative, 'index', False)

    for name in ('data_ledger', 'operator_ledger'):
        path = machine_resource_path(root, name)
        if not path.exists():
            for legacy in LEGACY_MACHINE_RESOURCE_PATHS.get(name, ()):
                candidate = _safe(root, legacy.as_posix())
                if candidate.exists():
                    path = candidate
                    break
        path = _safe(root, path.relative_to(root).as_posix())
        for row in _rows(path, diagnostics):
            _add(targets, row, path.relative_to(root).as_posix(), 'canonical', False)
    try:
        from wqb.semantic_publication import read_semantic_release, validate_semantic_receipt
        receipt = read_semantic_release(root)
        if receipt.get('release_id') is not None:
            path = _safe(root, Path(receipt['paths']['operator_ledger']).relative_to(root).as_posix())
            for row in _rows(path, diagnostics):
                _add(targets, row, path.relative_to(root).as_posix(), 'active', False)
            validate_semantic_receipt(root, receipt)
        dependencies['active_release'] = receipt
    except (OSError, ValueError, TypeError, KeyError) as exc:
        diagnostics.append(dict(path='machine/semantic_release.json', code='active_release_gap', message=str(exc)))

    inventory, materials = [], {}
    for key, target in sorted(targets.items()):
        material = [value for _, value in sorted(target.pop('materials').items())]
        materials[key] = material
        target['occurrences'] = [value for _, value in sorted(target['occurrences'].items())]
        target['scopes'] = [value for _, value in sorted(target['scopes'].items())]
        target['source_refs'] = [value for _, value in sorted(target['source_refs'].items())]
        verified_scopes = {_digest(scope): scope for item in material for scope in item['scopes']}
        target['source_validated_scopes'] = [value for _, value in sorted(verified_scopes.items())]
        target.update(source_validated=bool(material),
                      source_validation_scope='indexed_bytes_only', freshness_status='not_evaluated',
                      eligibility=dict(status='not_evaluated', research_eligible=False),
                      status='pending' if material else 'blocked', gaps=[], job_id=None)
        if not material:
            target['gaps'].append(dict(code='no_verified_material', message='Presence is not source validation'))
        if any(not occurrence['source_validated'] for occurrence in target['occurrences']):
            target['gaps'].append(dict(code='unverified_occurrences', message='Only exact source-validated occurrences supply job facts'))
        meanings = set()
        for occurrence in target['occurrences']:
            row = occurrence['row']
            field = row.get('field', row)
            description = field.get('field_description', field.get('description')) if isinstance(field, dict) else None
            if isinstance(description, str) and description:
                meanings.add(description)
        if len(meanings) > 1:
            target['gaps'].append(dict(code='conflicting_literal_meanings', meanings=sorted(meanings)))
        inventory.append(target)
    session.finalize()
    if preparation is not None and extra_paths:
        extra_session.finalize()
    contracts = _contracts(config)
    jobs, cached = _jobs(root, inventory, materials, contracts, config)
    raw_inventory = b''.join(_bytes(row) + b'\n' for row in inventory)
    identity = dict(root=str(root), contracts=contracts, sources=dependencies,
                    inventory_sha256=_hash(raw_inventory), jobs=jobs, diagnostics=diagnostics,
                    config={key: config[key] for key in defaults})
    if preparation is not None:
        identity['local_field_extracts'] = dict(config=local_extracts, result=preparation)
    key = _digest(identity)
    base = 'machine/semantic_jobs/' + key
    inventory_ref = _freeze(root, base + '/inventory.jsonl', raw_inventory)
    unresolved = [dict(d) for d in diagnostics if d['code'] in INVENTORY_GAP_CODES or d.get('inventory_unresolved')]
    coverage = dict(target_count=len(inventory), source_validated_targets=sum(t['source_validated'] for t in inventory),
                    prepared_targets=sum(t['status'] == 'prepared' for t in inventory),
                    blocked_targets=sum(t['status'] == 'blocked' for t in inventory),
                    inventory_complete=not unresolved, unresolved_inventory_sources=unresolved,
                    compiler_eligibility='not_evaluated', actual_start_consumption='not_evaluated')
    estimates = dict(label='estimates_not_billing', planned_call_count=len(jobs),
                     estimated_input_tokens=sum(j['estimated_input_tokens'] for j in jobs),
                     estimated_output_tokens=sum(j['estimated_output_tokens'] for j in jobs),
                     maximum_runtime_seconds=config['max_runtime_seconds'])
    plan = dict(schema_version=SCHEMA_VERSION, kind='full_semantic_compile_plan', root=str(root),
                content_key=key, status='prepared' if coverage['inventory_complete'] and coverage['blocked_targets'] == 0 else 'partial',
                plan_path=base + '/plan.json', identity=identity, inventory_ref=inventory_ref,
                jobs=jobs, diagnostics=diagnostics, coverage=coverage, estimates=estimates,
                budget=dict(model_call_budget=config['model_call_budget'], execution_authorized=False),
                model_calls=0, publication_authorized=False, research_authorized=False)
    if preparation is not None:
        plan['local_field_extracts'] = preparation
    _freeze(root, plan['plan_path'], _bytes(plan))
    # Cache counters are observations of preparation, never part of immutable identity.
    return dict(plan, estimates=dict(estimates, cached_jobs=cached, changed_jobs=len(jobs) - cached))
