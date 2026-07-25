"""notes-mcp: serve a folder of markdown notes to MCP clients over stdio.

Run it like this::

    NOTES_DIR=/path/to/notes python -m notes_mcp.server

The server shows both halves of MCP on the same little pile of files:

* **resources** are the nouns -- one registered per markdown file, so a client
  can list and fetch notes by URI (``notes:///business/pricing.md``);
* **tools** are the verbs -- ``search_notes``, ``list_notes``, ``read_note``.

Two rules worth internalising before editing this file:

1. **stdout belongs to the protocol.** stdio transport speaks JSON-RPC over
   stdout, so a single stray ``print()`` corrupts the stream and the client
   drops the connection. Every human-facing message goes to stderr through
   :func:`log`.
2. **Nothing is resolved at import time.** ``NOTES_DIR`` is read inside
   :func:`main`, so ``import notes_mcp.server`` works with no environment set
   and tests can introspect the app object.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import FunctionResource
from pydantic import AnyUrl

from . import search

# The FastMCP application. Module-level on purpose: tests import this object to
# inspect the registered tools and resources without starting a server.
mcp = FastMCP("notes-mcp")
app = mcp  # friendlier alias; the same object

# Set by configure_notes_dir(), which main() calls at startup -- never at import.
_notes_dir: Path | None = None


def log(message: str) -> None:
    """Print a human-facing message to stderr. Never use plain print() here:
    stdout carries the JSON-RPC protocol (see the module docstring)."""
    print(f"notes-mcp: {message}", file=sys.stderr, flush=True)


def notes_dir() -> Path:
    """The configured notes folder, or an error if configuration has not run."""
    if _notes_dir is None:
        raise RuntimeError(
            "notes folder is not configured yet -- call configure_notes_dir() "
            "(main() does this from NOTES_DIR at startup)"
        )
    return _notes_dir


def configure_notes_dir(raw_path: str | Path) -> Path:
    """Validate and remember the notes folder, returning its resolved path.

    Kept out of module import so that importing this module never touches the
    environment or the filesystem. Raises ``NotADirectoryError`` if the path is
    not an existing directory; ``main()`` turns that into a stderr message and a
    non-zero exit.
    """
    global _notes_dir
    resolved = Path(raw_path).expanduser().resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(f"NOTES_DIR is not an existing directory: {resolved}")
    _notes_dir = resolved
    return resolved


def _note_resource(base: Path, relpath: str) -> FunctionResource:
    """Build the resource object for one note.

    A ``FunctionResource`` rather than a plain ``FileResource`` so the read goes
    through :func:`search.load_note` -- the same UTF-8 decoding and the same
    containment check that the ``read_note`` tool uses. One door into the
    filesystem, checked once, used by both halves of the protocol.
    """

    def read_this_note() -> str:
        return search.load_note(base, relpath)

    return FunctionResource(
        uri=AnyUrl(search.note_uri(relpath)),
        name=relpath,
        description=f"Markdown note: {relpath}",
        mime_type="text/markdown",
        fn=read_this_note,
    )


def register_note_resources() -> int:
    """Scan the notes folder once and register one resource per note.

    Returns the number registered. A startup-time scan is deliberate: notes
    added later show up on the next restart, and live re-scanning is out of
    scope for this project.

    Why not a FastMCP resource *template* (``@mcp.resource("notes://{path}")``)?
    Two reasons, both verified against mcp 1.28: a ``{param}`` segment compiles
    to a regex that will not match across ``/``, so nested notes like
    ``business/pricing.md`` never match; and templates are advertised on
    ``resources/templates/list``, not ``resources/list``, so clients would see an
    empty note list.
    """
    base = notes_dir()
    count = 0
    for path in search.iter_note_files(base):
        mcp.add_resource(_note_resource(base, search.relpath_for(base, path)))
        count += 1
    return count


@mcp.tool()
def search_notes(query: str, max_results: int = 5) -> str:
    """Search all markdown notes for a text query. Returns the best-matching
    notes with the matching lines and their resource URIs. Use this first to
    find relevant notes, then read the full note (via read_note or its resource
    URI) if more context is needed.
    """
    if not query.strip():
        return (
            "I need something to search for. Try a word or phrase, e.g. "
            'search_notes(query="pricing"), or call list_notes to browse.'
        )
    hits = search.search_notes(notes_dir(), query, max_results, on_skip=log)
    return search.format_search_results(query, hits)


@mcp.tool()
def list_notes() -> str:
    """List every note this server can see, with its resource URI, size in bytes
    and last-modified date. The same set of notes as resources/list, offered as a
    tool because some clients do not surface resources to the model.
    """
    base = notes_dir()
    lines: list[str] = []
    for path in search.iter_note_files(base):
        relpath = search.relpath_for(base, path)
        try:
            info = path.stat()
        except OSError as exc:
            log(f"skipping {relpath}: {exc}")
            continue
        modified = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
        lines.append(
            f"- {relpath}  ({info.st_size} bytes, modified {modified})\n"
            f"  uri: {search.note_uri(relpath)}"
        )

    if not lines:
        # No absolute path here: it is the one thing the model cannot already
        # know, and the startup log in main() already records it for the human.
        return "No markdown notes found in the configured notes folder."
    return f"{len(lines)} note(s) available:\n\n" + "\n".join(lines)


@mcp.tool()
def read_note(path: str) -> str:
    """Read one note in full. Accepts either a notes:/// resource URI or a path
    relative to the notes folder, for example "business/pricing.md".
    """
    try:
        return search.load_note(notes_dir(), path)
    except search.NoteAccessError as exc:
        # A refusal is a normal answer, not a crash: one clean sentence for the
        # model, no traceback, and nothing written to stdout.
        return f"Cannot read that note: {exc}."
    except Exception as exc:
        # Deliberately broad. This tool's contract is that *whatever* a model
        # sends, it gets a sentence back rather than an exception -- and an
        # exception escaping here is reported to the client verbatim, which can
        # disclose the server's absolute paths. The detail goes to the log; the
        # client is told only what it already knows (its own input).
        log(f"failed to read {path!r}: {type(exc).__name__}: {exc}")
        return f"Cannot read that note: {path!r} could not be read."


def main() -> None:
    """Read NOTES_DIR, register the notes, and serve MCP over stdio."""
    raw_path = os.environ.get("NOTES_DIR", "").strip()
    if not raw_path:
        log(
            "NOTES_DIR is not set. Point it at a folder of .md files, e.g.\n"
            "  NOTES_DIR=/path/to/notes python -m notes_mcp.server"
        )
        sys.exit(1)

    try:
        base = configure_notes_dir(raw_path)
    except OSError as exc:  # NotADirectoryError and friends
        log(str(exc))
        sys.exit(1)

    count = register_note_resources()
    if count == 0:
        log(f"warning: no .md files found under {base}")
    log(f"serving {count} note(s) from {base} over stdio")

    # Blocks, reading JSON-RPC from stdin and writing it to stdout, until the
    # client disconnects.
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
