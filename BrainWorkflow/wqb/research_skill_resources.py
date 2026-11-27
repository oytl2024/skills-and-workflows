"""Small read-only Skill/report interface, independent of platform inventories."""
import hashlib
import os
from pathlib import Path, PurePosixPath


MAX_TEXT_BYTES = 512_000
MAX_TEXT_CHARS = 8000
MAX_DISCOVERY_FILES = 2000
ROOTS = ('skills/brain-research', 'researchreport')


def skill_knowledge(root: Path) -> bool:
    """Input: knowledge Path. Output: bool indicating the explicit research-Skill product entry exists."""
    return (Path(root) / 'skills/brain-research/SKILL.md').is_file()


def _path(root: Path, relative: str) -> Path:
    """Input: knowledge Path and relative string. Output: contained non-link path under an approved root."""
    if not isinstance(relative, str) or '\\' in relative or ':' in relative:
        raise ValueError('Skill paths must be relative POSIX paths')
    parts = PurePosixPath(relative)
    if parts.is_absolute() or '..' in parts.parts or not any(
            relative == prefix or relative.startswith(prefix + '/') for prefix in ROOTS):
        raise ValueError('only research Skill and report paths are readable')
    current = root.absolute()
    if any(parent.is_symlink() or parent.is_junction() for parent in (current, *current.parents)):
        raise ValueError('Skill root cannot traverse links')
    for part in parts.parts:
        current = current / part
        if current.is_symlink() or current.is_junction():
            raise ValueError('Skill resources cannot follow links')
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError('Skill resource escaped knowledge root')
    return current


def query_skill(root: Path, arguments: dict) -> dict:
    """Input: knowledge Path and paging/path dict. Output: Markdown guidance page or bounded path listing."""
    root = Path(root)
    if not isinstance(arguments, dict):
        raise ValueError('Skill arguments must be an object')
    if 'path' in arguments:
        if set(arguments) - {'path', 'start', 'length'}:
            raise ValueError('unknown Skill read arguments')
        start, length = arguments.get('start', 0), arguments.get('length', MAX_TEXT_CHARS)
        if type(start) is not int or start < 0 or type(length) is not int or not 1 <= length <= MAX_TEXT_CHARS:
            raise ValueError('invalid Skill text page')
        path = _path(root, arguments['path'])
        if path.suffix != '.md' or not path.is_file():
            raise ValueError('Skill resources must be existing Markdown files')
        with path.open('rb') as stream:
            bound = 2_000_000 if arguments['path'].startswith('researchreport/') else MAX_TEXT_BYTES
            raw = stream.read(bound + 1)
        if len(raw) > bound:
            raise ValueError('Skill document exceeds byte budget')
        text = raw.decode('utf-8')
        end = min(start + length, len(text))
        return dict(path=arguments['path'], text=text[start:end], start=start,
                    next_start=end if end < len(text) else None, total_chars=len(text),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    authority='research_guidance_not_platform_proof')
    if set(arguments) - {'offset', 'limit'}:
        raise ValueError('unknown Skill discovery arguments')
    offset, limit = arguments.get('offset', 0), arguments.get('limit', 50)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('invalid Skill discovery page')
    items = []
    for prefix in ROOTS:
        directory = _path(root, prefix)
        for parent, directories, names in os.walk(directory, followlinks=False):
            directories[:] = sorted(name for name in directories
                if not (Path(parent) / name).is_symlink() and not (Path(parent) / name).is_junction())
            for name in sorted(names):
                path = Path(parent) / name
                if path.suffix == '.md':
                    relative = path.relative_to(root).as_posix()
                    _path(root, relative)
                    items.append(dict(path=relative))
                    if len(items) > MAX_DISCOVERY_FILES:
                        raise ValueError('Skill discovery exceeds file budget')
    return dict(items=items[offset:offset + limit],
                next_offset=offset + limit if offset + limit < len(items) else None,
                authority='research_guidance_not_platform_proof')
