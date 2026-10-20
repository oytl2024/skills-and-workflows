"""Developer-only offline audit/demo; never invokes a model, platform or publication."""

import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wqb.hypothesis_design import MAX_JSON_BYTES, validate_hypothesis_design, compile_hypothesis_design
from wqb.knowledge_compile import audit_hypothesis_resources
from wqb.semantic_contracts import SemanticPolicy


PROTECTED_PARTS = {'.git', '.obsidian', '.superpowers', 'raw', 'machine', 'wiki',
                   'wqb', 'tests', 'scripts', 'configs', 'docs', 'management'}
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
PRODUCT_ROOT = Path(__file__).resolve().parents[1]


def _output_directory(source: Path, destination: Path, payload: dict) -> Path:
    """Input: source/destination Paths and input dict. Output: safe output Path; refuse source/authority overwrites."""
    absolute = destination.absolute()
    if any(part.casefold() in PROTECTED_PARTS for part in absolute.parts):
        raise ValueError('output must not be a source or canonical authority directory')
    if any(path.is_symlink() or path.is_junction() for path in (absolute, *absolute.parents)):
        raise ValueError('linked output directory refused')
    out = absolute.resolve()
    if source.resolve().is_relative_to(out):
        raise ValueError('output must not contain the input source')
    protected = [WORKSPACE_ROOT / 'knowledge', WORKSPACE_ROOT / 'runs', WORKSPACE_ROOT / 'archive',
                 PRODUCT_ROOT / 'runs']
    if isinstance(payload.get('knowledge_root'), str):
        protected.append(Path(payload['knowledge_root']))
    if any(out.is_relative_to(path.resolve()) for path in protected):
        raise ValueError('output must not be inside knowledge, live runs or archived authority')
    if any((parent / marker).exists() for parent in (out, *out.parents)
           for marker in ('run_state.json', 'runtime_control.json', 'run_manifest.json')):
        raise ValueError('output must not be inside a persisted run or job')
    if any((out / name).exists() for name in PROTECTED_PARTS):
        raise ValueError('output is an existing project or knowledge root')
    return out


def _write_outputs(out: Path, artifacts: dict, source: Path, payload: dict) -> None:
    """Input: safe directory Path/artifact dict. Output: None. Preflight all files; never overwrite differing content."""
    encoded = {name: (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
               for name, value in artifacts.items()}
    _output_directory(source, out, payload)
    for name, text in encoded.items():
        _output_directory(source, out, payload)
        path = out / name
        if path.is_symlink() or path.is_junction():
            raise ValueError('linked output artifact refused')
        if path.exists() and (not path.is_file() or path.read_bytes() != text):
            raise FileExistsError('different output already exists: ' + name)
    _output_directory(source, out, payload)
    out.mkdir(parents=True, exist_ok=True)
    for name, text in encoded.items():
        _output_directory(source, out, payload)
        path = out / name
        if path.exists():
            if path.is_symlink() or path.is_junction() or not path.is_file() or path.read_bytes() != text:
                raise FileExistsError('output changed during generation: ' + name)
        else:
            with path.open('xb') as stream:
                stream.write(text)
    _output_directory(source, out, payload)
    for name, text in encoded.items():
        path = out / name
        if path.is_symlink() or path.is_junction() or path.read_bytes() != text:
            raise ValueError('output changed before verification: ' + name)


def run_demo(source: Path, destination: Path, mode: str, policy: SemanticPolicy) -> dict:
    """Input: JSON source/output Paths, audit|demo str, SemanticPolicy. Output: deterministic result dict, explicit local artifacts only."""
    source = Path(source)
    if source.stat().st_size > MAX_JSON_BYTES:
        raise ValueError('oversized offline input')
    payload = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError('offline input requires an object')
    out = _output_directory(source, Path(destination), payload)
    design, drafts, experiments, diagnostics = None, [], [], []
    if mode == 'audit':
        if set(payload) != {'knowledge_root', 'scope', 'template_requirements'}:
            raise ValueError('audit input requires knowledge_root/scope/template_requirements')
        coverage = audit_hypothesis_resources(Path(payload['knowledge_root']), payload['scope'], payload['template_requirements'])
        diagnostics = coverage['coverage']['reasons']
        status = coverage['status']
    elif mode == 'demo':
        if set(payload) != {'resources', 'answer'} or not isinstance(payload['resources'], dict):
            raise ValueError('demo input requires resources and raw structured answer')
        resources = payload['resources']
        try:
            design = validate_hypothesis_design(payload['answer'], resources['evidence_pack'], policy)
        except (ValueError, TypeError, KeyError) as error:
            diagnostics.append(dict(code='invalid_design', message=str(error)))
        if design is not None:
            for row in design['designs']:
                compiled = compile_hypothesis_design(row, resources, resources['evidence_pack']['scope'])
                drafts.extend(compiled['drafts'])
                diagnostics.extend(compiled['rejections'])
                if compiled['experiment'] is not None:
                    experiments.append(compiled['experiment'])
        status = 'compiled' if experiments and not diagnostics else 'rejected'
        coverage = dict(partial=True, research_authorized=False, compiled_designs=len(experiments),
                        draft_count=len(drafts), rejection_count=len(diagnostics),
                        boundary='offline supplied-source compilation only, not measured results or platform readiness')
    else:
        raise ValueError('unsupported offline mode')
    _write_outputs(out, {'design.json': design, 'drafts.json': drafts, 'experiment.json': experiments,
                         'coverage.json': coverage, 'diagnostics.json': diagnostics}, source, payload)
    return dict(status=status, draft_count=len(drafts), research_authorized=False)


def main() -> int:
    """Input: developer CLI arguments. Output: JSON summary and exit code; zero only for accepted offline outcomes."""
    defaults = SemanticPolicy()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('audit', 'demo'), required=True)
    parser.add_argument('--evidence-pack', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--max-mechanisms', type=int, default=defaults.max_mechanisms)
    parser.add_argument('--max-conditions-per-mechanism', type=int, default=defaults.max_conditions_per_mechanism)
    args = parser.parse_args()
    try:
        result = run_demo(args.evidence_pack, args.output_dir, args.mode,
                          SemanticPolicy(args.max_mechanisms, args.max_conditions_per_mechanism))
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps(dict(status='rejected', error_type=type(error).__name__, message=str(error))))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in ('compiled', 'usable_subset') else 2


if __name__ == '__main__':
    raise SystemExit(main())
