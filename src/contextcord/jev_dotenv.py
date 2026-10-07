"""Secret-safe project-root dotenv loading for the optional Jev adapter."""
from __future__ import annotations

import os
import threading
from pathlib import Path


_LOCK = threading.RLock()


def ensure_jev_key(project_root: str | Path | None) -> tuple[bool, str]:
    """Load ``project_root/.env`` only when the process key is blank.

    The return value contains only presence and provenance labels.  The key is
    never returned, logged, placed in a bundle, or included in receipts.
    """
    with _LOCK:
        if os.environ.get("TYPESAFE_API_KEY", "").strip():
            return True, "process_environment"
        if "TYPESAFE_API_KEY" in os.environ:
            os.environ.pop("TYPESAFE_API_KEY")
        if project_root is None:
            return False, "not_configured"
        dotenv = Path(project_root).resolve() / ".env"
        if not dotenv.is_file():
            return False, "not_configured"
        try:
            from dotenv import load_dotenv
        except ImportError:
            return False, "python_dotenv_missing"
        try:
            load_dotenv(dotenv_path=dotenv, override=False)
        except Exception:
            return False, "dotenv_load_failed"
        return (True, "project_dotenv") if os.environ.get("TYPESAFE_API_KEY", "").strip() else (False, "not_configured")
