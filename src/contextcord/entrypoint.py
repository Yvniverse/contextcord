"""Primary console entry point with ContextCord's state namespace enabled."""

import os

from .cli import main as _main


def main(argv=None) -> int:
    os.environ.setdefault("CONTEXTCORD_INIT_STATE_DIR", ".contextcord")
    return _main(argv)
