"""Deprecated compatibility namespace for the pre-ContextCord package name.

The implementation now lives under :mod:`contextcord`.  Keeping this small
namespace package lets existing integrations import legacy module paths while
all new code and release metadata use the ContextCord identity.
"""

from pathlib import Path

import contextcord as _contextcord

# Make ``project_harness.<module>`` resolve the canonical implementation
# without copying policy code into a second package.
__path__ = [str(Path(_contextcord.__file__).resolve().parent)]

for _name in getattr(_contextcord, "__all__", ()):
    globals()[_name] = getattr(_contextcord, _name)

__all__ = list(getattr(_contextcord, "__all__", ()))
