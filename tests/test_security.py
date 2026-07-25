"""Group 2 -- the containment boundary (SPEC section 8.2).

Everything a client can name must resolve inside ``NOTES_DIR``: ``..`` segments,
percent-encoded ``..``, absolute paths and symlinks all have to be refused, and
refused *cleanly* -- one sentence for the model, never a traceback and never a
byte of the file that was asked for.

The refusal shows up in two different shapes, which is why each case is asserted
twice:

* the pure layer (``search.resolve_note_path`` / ``search.load_note``) **raises**
  ``search.NoteAccessError``;
* the ``read_note`` tool **returns text** starting ``"Cannot read that note: "``,
  because a refusal is a normal tool answer, not a protocol error.

The resource half of the protocol is covered too: a traversal URI is simply never
registered, and the per-note resource read runs through the same check.
"""

from __future__ import annotations

import pytest

from conftest import FIXTURE_NOTES, run_async
from notes_mcp import search, server

SECRET_MARKER = "SECRET-TOKEN-a11b22"

#: Every spelling of "give me a file outside the notes folder" that a model or a
#: malicious client might send.
ESCAPE_ATTEMPTS = [
    "../secret.md",
    "notes://../secret.md",
    "notes:///../secret.md",
    "notes:///..%2Fsecret.md",  # percent-encoded traversal: decoded before the check
    "nested/../../secret.md",
    "./../secret.md",
    "../../../../etc/passwd",
    "/etc/passwd",
    "notes:////etc/passwd",  # absolute path smuggled into the URI form
]


@pytest.fixture
def vault(tmp_path):
    """A small notes folder with a secret file sitting just outside it."""
    (tmp_path / "secret.md").write_text(f"# Secret\n\n{SECRET_MARKER}\n", encoding="utf-8")
    notes = tmp_path / "vault"
    (notes / "nested").mkdir(parents=True)
    (notes / "ok.md").write_text("# Ok\n\nnothing secret here\n", encoding="utf-8")
    (notes / "nested" / "deep.md").write_text("# Deep\n", encoding="utf-8")
    return notes


# --------------------------------------------------------------------------- #
# Pure layer: resolve_note_path / load_note raise
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("attempt", ESCAPE_ATTEMPTS)
def test_resolve_note_path_rejects_escapes(vault, attempt):
    with pytest.raises(search.NoteAccessError):
        search.resolve_note_path(vault, attempt)


@pytest.mark.parametrize("attempt", ESCAPE_ATTEMPTS)
def test_load_note_never_returns_content_from_outside(vault, attempt):
    with pytest.raises(search.NoteAccessError) as caught:
        search.load_note(vault, attempt)

    assert SECRET_MARKER not in str(caught.value)


def test_absolute_path_to_a_real_note_outside_is_rejected(vault):
    """pathlib's ``base / "/abs/path"`` *is* ``/abs/path`` -- the containment
    check is the only thing standing between a client and an arbitrary read."""
    outside = vault.parent / "secret.md"
    assert outside.is_file()

    with pytest.raises(search.NoteAccessError, match="outside the notes folder"):
        search.load_note(vault, str(outside))


def test_hidden_and_non_markdown_paths_are_refused(vault):
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "hidden.md").write_text("hidden\n", encoding="utf-8")
    (vault / "notes.txt").write_text("plain\n", encoding="utf-8")
    (vault / ".dotfile.md").write_text("dot\n", encoding="utf-8")

    with pytest.raises(search.NoteAccessError, match="hidden"):
        search.load_note(vault, ".obsidian/hidden.md")
    with pytest.raises(search.NoteAccessError, match="hidden"):
        search.load_note(vault, ".dotfile.md")
    with pytest.raises(search.NoteAccessError, match="markdown"):
        search.load_note(vault, "notes.txt")


def test_missing_and_empty_paths_are_refused(vault):
    with pytest.raises(search.NoteAccessError, match="no note at"):
        search.load_note(vault, "nope.md")
    with pytest.raises(search.NoteAccessError, match="no note path was given"):
        search.load_note(vault, "")
    with pytest.raises(search.NoteAccessError):
        search.load_note(vault, "   ")


def test_legitimate_paths_still_resolve(vault):
    assert search.resolve_note_path(vault, "ok.md") == (vault / "ok.md").resolve()
    assert search.resolve_note_path(vault, "notes:///ok.md") == (vault / "ok.md").resolve()
    assert (
        search.resolve_note_path(vault, "notes:///nested/deep.md")
        == (vault / "nested" / "deep.md").resolve()
    )
    # A ".." that stays inside the folder is fine -- containment, not paranoia.
    assert search.resolve_note_path(vault, "nested/../ok.md") == (vault / "ok.md").resolve()


def test_symlink_pointing_outside_is_rejected(vault):
    """Stretch goal 4: ``Path.resolve()`` follows the link, so the escape is
    judged by where it lands. Skipped where symlinks cannot be created."""
    link = vault / "link.md"
    try:
        link.symlink_to(vault.parent / "secret.md")
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform dependent
        pytest.skip(f"cannot create symlinks here: {exc}")

    with pytest.raises(search.NoteAccessError, match="outside the notes folder"):
        search.load_note(vault, "link.md")
    # And it is not offered in the first place.
    assert "link.md" not in [
        search.relpath_for(vault, path) for path in search.find_note_files(vault)
    ]


# --------------------------------------------------------------------------- #
# Tool layer: read_note returns a refusal instead of raising
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("attempt", ESCAPE_ATTEMPTS)
def test_read_note_tool_refuses_escapes(use_notes_dir, vault, attempt):
    use_notes_dir(vault)

    answer = server.read_note(attempt)

    assert answer.startswith("Cannot read that note: ")
    assert SECRET_MARKER not in answer


def test_read_note_tool_refuses_a_real_file_just_outside_the_fixtures(notes_server):
    """``tests/fixtures/README.md`` is a genuine markdown file one level up: it
    exists, so only the containment check can stop it being served."""
    outside = FIXTURE_NOTES.parent / "README.md"
    assert outside.is_file()

    answer = server.read_note("../README.md")

    assert "outside the notes folder" in answer
    assert "# Test fixtures" not in answer
    assert answer.startswith("Cannot read that note: ")


def test_read_note_tool_refuses_hidden_non_markdown_and_missing(notes_server):
    hidden = server.read_note(".obsidian/hidden.md")
    assert "hidden file or folder" in hidden
    assert "widget" not in hidden  # the decoy's contents never leak

    assert "not a markdown (.md) note" in server.read_note("nested/ignored.txt")
    assert "there is no note at" in server.read_note("nope.md")
    assert "no note path was given" in server.read_note("")
    assert "no note path was given" in server.read_note("   ")


def test_read_note_tool_reads_legitimate_notes(notes_server):
    by_relpath = server.read_note("Spaced Note.md")
    by_uri = server.read_note("notes:///Spaced%20Note.md")

    assert by_relpath.startswith("# Spaced Note")
    assert by_uri == by_relpath
    assert server.read_note("notes:///nested/deep.md").startswith("# Deep")


def test_read_note_never_raises_for_bad_input(notes_server):
    """Whatever a model sends, the tool answers with a sentence."""
    for attempt in ESCAPE_ATTEMPTS + ["", "   ", "nope.md", "nested", "."]:
        answer = server.read_note(attempt)
        assert isinstance(answer, str)
        assert answer.startswith("Cannot read that note: ")


# --------------------------------------------------------------------------- #
# Resource layer: same check, other half of the protocol
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "uri",
    ["notes:///../secret.md", "notes:///../README.md", "notes:///.obsidian/hidden.md"],
)
def test_resource_read_refuses_unlisted_uris(notes_server, uri):
    # Traversal URIs were never registered, so the resource manager refuses
    # before any file is touched. (pydantic's AnyUrl also normalises "..", which
    # is a second reason the read cannot land outside.)
    with pytest.raises(ValueError, match="Unknown resource"):
        run_async(notes_server.mcp.read_resource(uri))


def test_registered_resources_all_live_inside_the_notes_folder(notes_server):
    resources = run_async(notes_server.mcp.list_resources())

    base = FIXTURE_NOTES.resolve()
    for resource in resources:
        resolved = search.resolve_note_path(base, str(resource.uri))
        assert resolved.is_relative_to(base)
    assert not any("obsidian" in str(resource.uri) for resource in resources)


def test_resource_read_goes_through_the_containment_check(notes_server):
    """The resource objects are not FileResources: their read calls
    ``search.load_note``, so a resource pointed outside would still be refused.

    FastMCP wraps whatever the read function raises in a ``ValueError``, so the
    NoteAccessError message travels out as text -- the point is that the refusal
    happens at all and no file content comes back.
    """
    escaping = server._note_resource(FIXTURE_NOTES, "../README.md")

    with pytest.raises(ValueError, match="outside the notes folder") as caught:
        run_async(escaping.read())
    assert "# Test fixtures" not in str(caught.value)

    legit = server._note_resource(FIXTURE_NOTES, "alpha.md")
    assert run_async(legit.read()).startswith("# Alpha")


# --------------------------------------------------------------------------- #
# Regressions from the security audit
# --------------------------------------------------------------------------- #
#
# Both cases below reach Path.resolve() and make it raise something that is NOT
# an OSError -- RuntimeError for a symlink loop, ValueError for a NUL byte -- so
# they slipped past read_note's original `except OSError` and were reported to
# the client as protocol errors carrying the server's absolute NOTES_DIR path.
# search.safe_resolve() now converts every resolve() failure into a
# NoteAccessError that echoes only the caller's own input.


def test_circular_symlink_is_refused_without_leaking_the_notes_path(
    tmp_path, use_notes_dir
):
    """A symlink loop must not turn into a RuntimeError with an absolute path."""
    vault = tmp_path / "vault"
    vault.mkdir()
    try:
        (vault / "loopa.md").symlink_to(vault / "loopb.md")
        (vault / "loopb.md").symlink_to(vault / "loopa.md")
    except OSError:  # pragma: no cover - platform without symlinks
        pytest.skip("symlinks not supported here")

    resolved = use_notes_dir(vault)

    with pytest.raises(search.NoteAccessError):
        search.load_note(vault, "loopa.md")

    answer = server.read_note("loopa.md")
    assert answer.startswith("Cannot read that note: ")
    # The whole point: the client learns nothing about the host filesystem.
    assert str(resolved) not in answer
    assert str(tmp_path) not in answer

    # A loop anywhere in the folder must not break scanning either.
    assert search.find_note_files(vault) == []


def test_nul_byte_is_refused_even_through_a_well_formed_uri(tmp_path, use_notes_dir):
    """``notes:///ok%00.md`` decodes to a real NUL before the containment check."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "ok.md").write_text("fine\n", encoding="utf-8")
    use_notes_dir(vault)

    for probe in ["ok\x00.md", "notes:///ok%00.md", "\x00"]:
        with pytest.raises(search.NoteAccessError):
            search.load_note(vault, probe)
        answer = server.read_note(probe)
        assert answer.startswith("Cannot read that note: "), f"{probe!r} -> {answer!r}"
