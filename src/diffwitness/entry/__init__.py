"""Public DiffWitness v0.3 frontend.

The package form intentionally owns `diffwitness.entry` for the 0.3 command surface. The legacy
single-file entry module remains in source history for compatibility during the release transition,
but Python resolves this package first and the public console script imports `main` from here.
"""

from ..frontend import FrontendError, main

__all__ = ["FrontendError", "main"]
