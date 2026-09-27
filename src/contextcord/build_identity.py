"""Content identity of the executing core, independent of installation path."""
from pathlib import Path
from . import __version__
from .util import sha256_file, sha256_json


def build_identity() -> dict:
    root = Path(__file__).resolve().parent
    files = {p.relative_to(root).as_posix(): sha256_file(p)
             for p in sorted(root.rglob('*'))
             if p.is_file() and p.suffix in {'.py', '.json', '.toml'}
             and '__pycache__' not in p.parts}
    return {'version': __version__, 'sha256': sha256_json(files), 'file_count': len(files)}
