"""Shared fixtures and constants for the notes-mcp test suite.

Two things here are worth knowing before adding tests:

1. **``tests/fixtures/notes/`` is the one notes folder the server-level tests
   use.** ``server.register_note_resources()`` mutates the single module-level
   ``FastMCP`` app, so registering two different folders in one pytest process
   would leave stale resources behind. The session-scoped :func:`notes_server`
   fixture therefore configures that folder exactly once, and every test that
   touches ``server.mcp`` depends on it.
2. **Everything that needs a throwaway folder uses the pure ``search`` module**
   with ``tmp_path`` instead -- those functions take the notes directory as an
   argument, so they need no global state at all. Where a *tool* has to run
   against a temporary folder, monkeypatch ``server._notes_dir`` (see
   :func:`use_notes_dir`) rather than re-registering resources.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Coroutine, Iterator, Mapping

import pytest

from notes_mcp import search, server

# --------------------------------------------------------------------------- #
# Where things live
# --------------------------------------------------------------------------- #

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
FIXTURE_NOTES = TESTS_DIR / "fixtures" / "notes"
DEMO_NOTES = REPO_ROOT / "demo-notes"

#: The five in-scope notes in tests/fixtures/notes, in the order the scanner
#: must return them (plain ASCII sort on the relative path -- uppercase "S"
#: sorts before lowercase letters). See tests/fixtures/README.md.
FIXTURE_RELPATHS: list[str] = [
    "Spaced Note.md",
    "alpha.md",
    "beta.md",
    "gamma.md",
    "nested/deep.md",
]

#: The URIs those notes must be published under -- three slashes, percent-encoded.
FIXTURE_URIS: list[str] = [
    "notes:///Spaced%20Note.md",
    "notes:///alpha.md",
    "notes:///beta.md",
    "notes:///gamma.md",
    "notes:///nested/deep.md",
]

#: Files in the fixture folder that must never be seen: hidden dir, non-markdown.
FIXTURE_EXCLUDED = [".obsidian/hidden.md", "nested/ignored.txt"]

EXPECTED_TOOL_NAMES = {"search_notes", "list_notes", "read_note"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def run_async(coro: Coroutine[Any, Any, Any], timeout: float = 30.0) -> Any:
    """Run one coroutine to completion with a finite timeout.

    FastMCP's ``list_tools`` / ``list_resources`` / ``read_resource`` are async
    and this suite installs no asyncio pytest plugin, so tests drive them
    through here. The timeout means a hang fails the test instead of wedging the
    whole run.
    """
    return asyncio.run(asyncio.wait_for(coro, timeout))


def write_notes(root: Path, files: Mapping[str, str]) -> Path:
    """Create a throwaway notes folder from a ``{relpath: text}`` mapping."""
    for relpath, text in files.items():
        target = root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def relpaths_of(notes_dir: Path, paths: list[Path]) -> list[str]:
    """Relative, forward-slashed paths for a list of scanned files."""
    return [search.relpath_for(notes_dir, path) for path in paths]


def fixture_text(relpath: str) -> str:
    """The on-disk text of one fixture note, read the same way the server does."""
    return search.read_note_text(FIXTURE_NOTES / relpath)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def notes_server():
    """The configured server module: notes dir set, resources registered once.

    Session-scoped so ``register_note_resources()`` runs a single time for the
    whole process (see the module docstring).
    """
    server.configure_notes_dir(FIXTURE_NOTES)
    registered = server.register_note_resources()
    assert registered == len(FIXTURE_RELPATHS), (
        f"expected {len(FIXTURE_RELPATHS)} fixture notes to register, got {registered}"
    )
    return server


@pytest.fixture
def use_notes_dir(notes_server, monkeypatch) -> Iterator[Any]:
    """Point the *tools* at another folder for the duration of one test.

    Only the notes-dir global moves; the registered resources are left alone, so
    this cannot corrupt the shared app object. monkeypatch restores the fixture
    folder afterwards.
    """

    def _use(path: Path) -> Path:
        resolved = Path(path).resolve()
        monkeypatch.setattr(server, "_notes_dir", resolved)
        return resolved

    yield _use
