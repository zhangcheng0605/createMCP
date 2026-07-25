"""notes-mcp: a small, read-only MCP server over a folder of markdown notes.

Launch it with::

    NOTES_DIR=/path/to/notes python -m notes_mcp.server

This package deliberately does nothing at import time (no environment lookups,
no filesystem scanning) so that tests can import it freely.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
