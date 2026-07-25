"""Group 3 -- what counts as a note, and how it is addressed (SPEC section 8.3).

Hidden directories skipped, non-``.md`` files ignored, nested folders walked, and
the ``notes:///`` URI round-tripping for a filename with a space -- the case that
makes the three-slash scheme non-negotiable (SPEC section 5).

The fixture folder is built to make regressions loud rather than quiet:
``nested/ignored.txt`` and ``.obsidian/hidden.md`` are both stuffed with the terms
the search tests rank on, so a scanner that picks them up fails several tests at
once instead of silently widening the server's reach.
"""

from __future__ import annotations

import pytest

from conftest import (
    DEMO_NOTES,
    FIXTURE_EXCLUDED,
    FIXTURE_NOTES,
    FIXTURE_RELPATHS,
    FIXTURE_URIS,
    relpaths_of,
    run_async,
    write_notes,
)
from notes_mcp import search, server


def scanned(notes_dir) -> list[str]:
    return relpaths_of(notes_dir, search.find_note_files(notes_dir))


# --------------------------------------------------------------------------- #
# Which files are in scope
# --------------------------------------------------------------------------- #


def test_scan_finds_exactly_the_five_fixture_notes_in_order():
    assert scanned(FIXTURE_NOTES) == FIXTURE_RELPATHS


def test_scan_is_deterministic():
    assert scanned(FIXTURE_NOTES) == scanned(FIXTURE_NOTES)


def test_hidden_directories_are_skipped():
    hidden = FIXTURE_NOTES / ".obsidian" / "hidden.md"
    assert hidden.is_file(), "fixture missing: the hidden decoy must exist to be skipped"

    found = scanned(FIXTURE_NOTES)

    assert ".obsidian/hidden.md" not in found
    assert not any(part.startswith(".") for relpath in found for part in relpath.split("/"))


def test_non_markdown_files_are_ignored():
    assert (FIXTURE_NOTES / "nested" / "ignored.txt").is_file()

    found = scanned(FIXTURE_NOTES)

    assert "nested/ignored.txt" not in found
    assert all(relpath.endswith(".md") for relpath in found)


def test_nested_folders_are_found():
    assert "nested/deep.md" in scanned(FIXTURE_NOTES)


def test_excluded_fixtures_never_reach_search_or_listing(notes_server):
    """Belt and braces: the decoys outrank every real note on every query used in
    the suite, so if they ever leak this is the test that names them."""
    listing = server.list_notes()
    results = server.search_notes("widget", max_results=20)

    for excluded in FIXTURE_EXCLUDED:
        assert excluded not in listing
        assert excluded not in results


def test_hidden_files_and_deeper_hidden_dirs_are_skipped(tmp_path):
    write_notes(
        tmp_path,
        {
            "visible.md": "hello\n",
            ".hidden-note.md": "hidden top-level file\n",
            ".obsidian/workspace.md": "vault internals\n",
            "sub/.git/config.md": "git internals\n",
            "sub/.hidden.md": "hidden nested file\n",
            "sub/deep/deeper/buried.md": "three levels down\n",
        },
    )

    assert scanned(tmp_path) == ["sub/deep/deeper/buried.md", "visible.md"]


def test_other_extensions_and_bare_names_are_ignored(tmp_path):
    write_notes(
        tmp_path,
        {
            "note.md": "yes\n",
            "note.markdown": "no\n",
            "note.txt": "no\n",
            "README": "no\n",
            "sub/data.json": "no\n",
        },
    )

    assert scanned(tmp_path) == ["note.md"]


def test_directories_named_like_notes_are_not_notes(tmp_path):
    (tmp_path / "folder.md").mkdir()
    (tmp_path / "folder.md" / "real.md").write_text("inside\n", encoding="utf-8")

    assert scanned(tmp_path) == ["folder.md/real.md"]


def test_empty_folder_scans_and_lists_cleanly(tmp_path, use_notes_dir):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert scanned(empty) == []

    use_notes_dir(empty)
    message = server.list_notes()
    assert message == "No markdown notes found in the configured notes folder."
    # The empty-folder message used to interpolate the resolved NOTES_DIR, which
    # handed the model the server's absolute path in ordinary (non-error) tool
    # output -- the one thing about the host it cannot otherwise learn.
    assert str(empty.resolve()) not in message
    assert server.search_notes("anything").startswith('No notes matched "anything".')


def test_a_symlink_to_a_note_next_door_is_not_listed_twice(tmp_path):
    """One file, one URI. (Also guards the crash that used to follow: the sort
    key and relpath_for must agree about which path a symlink refers to.)"""
    write_notes(tmp_path, {"real.md": "content\n"})
    try:
        (tmp_path / "alias.md").symlink_to(tmp_path / "real.md")
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform dependent
        pytest.skip(f"cannot create symlinks here: {exc}")

    assert scanned(tmp_path) == ["real.md"]


# --------------------------------------------------------------------------- #
# URIs
# --------------------------------------------------------------------------- #


def test_uri_uses_three_slashes_and_percent_encodes_spaces():
    assert search.URI_PREFIX == "notes:///"
    assert search.note_uri("Spaced Note.md") == "notes:///Spaced%20Note.md"
    # quote() leaves "/" alone, so nesting stays readable.
    assert search.note_uri("nested/deep.md") == "notes:///nested/deep.md"
    assert search.note_uri("business/My Note 2026.md") == "notes:///business/My%20Note%202026.md"


def test_fixture_uris_are_exactly_as_documented():
    assert [search.note_uri(relpath) for relpath in FIXTURE_RELPATHS] == FIXTURE_URIS


@pytest.mark.parametrize("relpath", FIXTURE_RELPATHS + ["café.md", "a/b c/d+e&f.md"])
def test_uri_round_trip(relpath):
    assert search.relpath_from_uri(search.note_uri(relpath)) == relpath


def test_relpath_from_uri_accepts_the_forms_a_model_may_send():
    assert search.relpath_from_uri("notes:///alpha.md") == "alpha.md"
    assert search.relpath_from_uri("notes://alpha.md") == "alpha.md"  # sloppy two-slash form
    assert search.relpath_from_uri("NOTES:///alpha.md") == "alpha.md"  # scheme is case-insensitive
    assert search.relpath_from_uri("  notes:///alpha.md  ") == "alpha.md"
    assert search.relpath_from_uri("alpha.md") == "alpha.md"  # bare relative path
    assert search.relpath_from_uri("notes:///nested/deep.md") == "nested/deep.md"


def test_uri_round_trip_reaches_the_file_on_disk(tmp_path):
    """The full loop: scan -> URI -> back to a path -> read the right bytes."""
    write_notes(
        tmp_path,
        {
            "Spaced Name.md": "# spaced\n",
            "café.md": "# unicode\n",
            "sub folder/inner note.md": "# nested and spaced\n",
        },
    )

    for path in search.find_note_files(tmp_path):
        relpath = search.relpath_for(tmp_path, path)
        uri = search.note_uri(relpath)
        assert " " not in uri
        assert search.resolve_note_path(tmp_path, uri) == path.resolve()
        assert search.load_note(tmp_path, uri) == path.read_text(encoding="utf-8")

    assert search.load_note(tmp_path, "notes:///caf%C3%A9.md") == "# unicode\n"
    assert search.load_note(tmp_path, "notes:///sub%20folder/inner%20note.md").endswith("spaced\n")


def test_relpath_for_is_forward_slashed_and_relative():
    path = FIXTURE_NOTES / "nested" / "deep.md"
    assert search.relpath_for(FIXTURE_NOTES, path) == "nested/deep.md"


# --------------------------------------------------------------------------- #
# What the two halves of the protocol advertise
# --------------------------------------------------------------------------- #


def test_registered_resources_match_the_scan(notes_server):
    resources = run_async(notes_server.mcp.list_resources())

    assert [str(resource.uri) for resource in resources] == FIXTURE_URIS
    assert [resource.name for resource in resources] == FIXTURE_RELPATHS
    assert {resource.mimeType for resource in resources} == {"text/markdown"}


def test_resource_read_returns_the_notes_own_text(notes_server):
    contents = run_async(notes_server.mcp.read_resource("notes:///Spaced%20Note.md"))

    assert len(contents) == 1
    assert contents[0].content == (FIXTURE_NOTES / "Spaced Note.md").read_text(encoding="utf-8")
    assert contents[0].mime_type == "text/markdown"


def test_no_resource_templates_are_advertised(notes_server):
    """Concrete resources only -- a "notes://{path}" template would neither match
    nested paths nor show up in resources/list (SPEC section 5)."""
    assert run_async(notes_server.mcp.list_resource_templates()) == []


def test_list_notes_tool_mirrors_resources_list(notes_server):
    listing = server.list_notes()

    assert listing.startswith("5 note(s) available:")
    for relpath, uri in zip(FIXTURE_RELPATHS, FIXTURE_URIS):
        assert relpath in listing
        assert f"uri: {uri}" in listing
    assert "bytes, modified " in listing
    # Same order as the scan and the resource list.
    positions = [listing.index(uri) for uri in FIXTURE_URIS]
    assert positions == sorted(positions)


# --------------------------------------------------------------------------- #
# The demo folder the README points at (SPEC section 11)
# --------------------------------------------------------------------------- #


def test_demo_notes_folder_is_shaped_for_the_demo():
    relpaths = scanned(DEMO_NOTES)

    assert 8 <= len(relpaths) <= 12, relpaths
    assert any("/" in relpath for relpath in relpaths), "needs at least one nested note"
    assert any(" " in relpath for relpath in relpaths), "needs a filename with a space"
    # Every demo note must survive the URI round trip, spaces and all.
    for relpath in relpaths:
        assert search.relpath_from_uri(search.note_uri(relpath)) == relpath


# --------------------------------------------------------------------------- #
# Regressions from the spec-compliance audit
# --------------------------------------------------------------------------- #


def test_hidden_note_reached_through_a_file_symlink_is_not_advertised(tmp_path):
    """A non-hidden symlink must not smuggle a hidden note into the listing.

    The scanner used to test the *unresolved* path for hidden segments while
    yielding the *resolved* one, so `link.md -> .obsidian/workspace-notes.md`
    published the hidden note in resources/list and leaked its text through
    search snippets -- while every read of it was refused, because the reader
    checked the resolved path. Scanner and reader now share in_scope_relpath().
    """
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "workspace-notes.md").write_text(
        "SECRET-INTERNALS\n", encoding="utf-8"
    )
    (vault / "real.md").write_text("an ordinary note\n", encoding="utf-8")
    try:
        (vault / "link.md").symlink_to(vault / ".obsidian" / "workspace-notes.md")
    except OSError:  # pragma: no cover - platform without symlinks
        pytest.skip("symlinks not supported here")

    assert scanned(vault) == ["real.md"]
    # And the hidden text must not surface through search either.
    assert search.search_notes(vault, "SECRET-INTERNALS") == []


def test_scanner_and_reader_agree_on_uppercase_md_extension(tmp_path, use_notes_dir):
    """`.MD` must be either listed *and* readable, or neither -- never one only.

    The scanner globbed `*.md` (case-sensitive on Linux) while the reader
    accepted `suffix.lower() == ".md"`, so `UPPER.MD` was unreachable through
    resources/list yet served in full by read_note.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "UPPER.MD").write_text("# upper\n", encoding="utf-8")
    (vault / "lower.md").write_text("# lower\n", encoding="utf-8")
    use_notes_dir(vault)

    listed = "UPPER.MD" in scanned(vault)
    readable = not server.read_note("UPPER.MD").startswith("Cannot read that note:")
    assert listed == readable, f"listed={listed} readable={readable}"
    # This project's choice: case-insensitive suffix, so both are in scope.
    assert listed and readable
    assert scanned(vault) == ["UPPER.MD", "lower.md"]
