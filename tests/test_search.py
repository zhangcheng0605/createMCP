"""Group 1 -- search behaviour (SPEC section 8.1).

Ranking, the phrase bonus, tie-breaking, the empty query, and ``max_results``
clamping. Almost everything here talks to the pure ``notes_mcp.search`` module,
which takes the notes folder as an argument and needs no MCP machinery; the last
section checks that the ``search_notes`` *tool* wraps those results in the text a
model actually receives.

Term counts for the fixture notes are documented in tests/fixtures/README.md and
are load-bearing: ``widget`` appears 4x in alpha.md, 2x in beta.md, 1x in
gamma.md, and the two decoy files (``nested/ignored.txt``, ``.obsidian/hidden.md``)
are stuffed with it so that a scanning regression breaks the ranking loudly.
"""

from __future__ import annotations

import pytest

from conftest import FIXTURE_NOTES, fixture_text, write_notes
from notes_mcp import search, server


def relpaths(hits) -> list[str]:
    return [hit.relpath for hit in hits]


# --------------------------------------------------------------------------- #
# Finding a known term
# --------------------------------------------------------------------------- #


def test_finds_a_known_term_in_the_fixtures():
    hits = search.search_notes(FIXTURE_NOTES, "gizmo")

    assert relpaths(hits) == ["alpha.md"]
    hit = hits[0]
    assert hit.uri == "notes:///alpha.md"
    assert hit.score == 1
    assert hit.lines == ["This file also mentions gizmo exactly once."]


def test_search_is_case_insensitive():
    upper = search.search_notes(FIXTURE_NOTES, "WIDGET")
    lower = search.search_notes(FIXTURE_NOTES, "widget")

    assert relpaths(upper) == relpaths(lower)
    assert [hit.score for hit in upper] == [hit.score for hit in lower]


def test_no_match_returns_no_hits_and_a_helpful_message():
    hits = search.search_notes(FIXTURE_NOTES, "zzznotfound")
    assert hits == []

    text = search.format_search_results("zzznotfound", hits)
    assert text.startswith('No notes matched "zzznotfound".')
    assert "broader" in text
    assert "list_notes" in text


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #


def test_more_hits_ranks_first():
    hits = search.search_notes(FIXTURE_NOTES, "widget")

    # alpha (4 occurrences) > beta (2) > gamma (1); the other two notes have none.
    assert relpaths(hits) == ["alpha.md", "beta.md", "gamma.md"]
    scores = [hit.score for hit in hits]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > scores[1] > scores[2]


def test_phrase_bonus_beats_more_scattered_words():
    """The one test the +2 phrase bonus exists for.

    ``Spaced Note.md`` contains 'quantum' twice and 'ferret' once (3 word hits)
    but never side by side. ``nested/deep.md`` has each word once (2 word hits)
    plus the intact phrase, so +2 puts it in front. Remove the bonus and this
    ordering flips -- which is exactly what it is guarding.
    """
    hits = search.search_notes(FIXTURE_NOTES, "quantum ferret")

    assert relpaths(hits) == ["nested/deep.md", "Spaced Note.md"]

    deep, spaced = hits
    assert deep.score == 4  # 1 + 1 word hits, + PHRASE_BONUS for the intact phrase
    assert spaced.score == 3  # 2 + 1 word hits, no intact phrase
    assert search.PHRASE_BONUS == 2


def test_phrase_bonus_is_case_insensitive_too():
    assert search.score_text("A Quantum FERRET appears", "quantum ferret") == 4


def test_score_text_counts_words_plus_intact_phrases():
    # 3 single-word hits + 1 intact phrase * PHRASE_BONUS.
    assert search.score_text("value based pricing", "value based pricing") == 5
    # Words present but never adjacent: no bonus.
    assert search.score_text("value. based. pricing.", "value based pricing") == 3
    assert search.score_text("nothing relevant here", "quantum ferret") == 0


def test_single_word_query_counts_each_occurrence_once():
    """A one-word query gets no phrase bonus: the 'phrase' is the word itself,
    which the word count already covered (documented in search.score_text)."""
    assert search.score_text("Pricing pricing", "pricing") == 2


def test_matching_is_substring_based_no_word_boundaries():
    # Deliberately simple: no stemming, no boundaries (documented in the spec).
    assert search.score_text("a catalogue of cats", "cat") == 2


def test_tie_break_is_relpath_ascending():
    hits = search.search_notes(FIXTURE_NOTES, "tiebreak")

    assert relpaths(hits) == ["beta.md", "gamma.md"]
    assert hits[0].score == hits[1].score  # the ordering is purely the tie-break


def test_tie_break_ignores_filesystem_order(tmp_path):
    """Created newest-first, still returned alphabetically."""
    write_notes(
        tmp_path,
        {
            "zulu.md": "term\n",
            "mike.md": "term\n",
            "alpha.md": "term\n",
            "nested/bravo.md": "term\n",
        },
    )

    hits = search.search_notes(tmp_path, "term")

    assert relpaths(hits) == ["alpha.md", "mike.md", "nested/bravo.md", "zulu.md"]
    assert len({hit.score for hit in hits}) == 1


# --------------------------------------------------------------------------- #
# Empty query
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("query", ["", "   ", "\t\n"])
def test_blank_query_is_not_an_error(query):
    assert search.query_words(query) == []
    assert search.search_notes(FIXTURE_NOTES, query) == []
    assert search.score_text("anything at all", query) == 0
    assert search.matching_lines("anything at all", query) == []


@pytest.mark.parametrize("query", ["", "   "])
def test_blank_query_tool_answers_with_a_friendly_message(notes_server, query):
    text = server.search_notes(query)

    assert "I need something to search for" in text
    assert "list_notes" in text


# --------------------------------------------------------------------------- #
# max_results
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "given, expected",
    [
        (0, 1),
        (-3, 1),
        (1, 1),
        (5, 5),
        (20, 20),
        (21, 20),
        (99, 20),
        ("4", 4),  # models happily send numbers as strings
        (None, 1),
        ("banana", 1),
    ],
)
def test_max_results_is_clamped(given, expected):
    assert search.clamp_max_results(given) == expected


def test_search_honours_and_clamps_max_results():
    assert relpaths(search.search_notes(FIXTURE_NOTES, "widget", max_results=1)) == ["alpha.md"]
    assert relpaths(search.search_notes(FIXTURE_NOTES, "widget", max_results=2)) == [
        "alpha.md",
        "beta.md",
    ]
    # 0 clamps up to 1 ...
    assert len(search.search_notes(FIXTURE_NOTES, "widget", max_results=0)) == 1
    # ... and a huge value cannot invent notes that do not match.
    assert len(search.search_notes(FIXTURE_NOTES, "widget", max_results=999)) == 3


def test_search_never_returns_more_than_the_upper_clamp(tmp_path):
    write_notes(tmp_path, {f"note{index:02d}.md": "term\n" for index in range(30)})

    hits = search.search_notes(tmp_path, "term", max_results=999)

    assert len(hits) == search.MAX_MAX_RESULTS == 20


# --------------------------------------------------------------------------- #
# Snippets
# --------------------------------------------------------------------------- #


def test_at_most_three_matching_lines_per_note():
    hits = search.search_notes(FIXTURE_NOTES, "widget")
    alpha = hits[0]

    # alpha.md has four separate lines containing "widget"; only three are shown.
    assert fixture_text("alpha.md").lower().count("widget") == 4
    assert len(alpha.lines) == search.MAX_LINES_PER_NOTE == 3
    assert all("widget" in line for line in alpha.lines)
    assert "A fourth and final widget reference" not in " ".join(alpha.lines)


def test_snippet_lines_are_whitespace_collapsed_and_truncated(tmp_path):
    long_line = "widget " + ("padding " * 60)
    write_notes(tmp_path, {"messy.md": f"   widget\tspaced   out  \n\n{long_line}\n"})

    lines = search.matching_lines((tmp_path / "messy.md").read_text(), "widget")

    assert lines[0] == "widget spaced out"
    assert len(lines[1]) <= search.MAX_LINE_CHARS == 150
    assert lines[1].endswith("...")


def test_matching_lines_limit_is_configurable():
    text = "\n".join(f"widget line {index}" for index in range(10))

    assert len(search.matching_lines(text, "widget", limit=2)) == 2
    assert search.matching_lines(text, "widget", limit=1, max_chars=8) == ["widge..."]


# --------------------------------------------------------------------------- #
# Skipping unsearchable files
# --------------------------------------------------------------------------- #


def test_oversized_files_are_skipped_while_searching(tmp_path):
    """The 2 MB cap applies to search scanning only, and skips are reported."""
    write_notes(tmp_path, {"small.md": "widget\n"})
    fat = tmp_path / "huge.md"
    fat.write_text("widget\n" + ("x" * (search.MAX_SEARCH_FILE_BYTES + 1)), encoding="utf-8")

    skipped: list[str] = []
    hits = search.search_notes(tmp_path, "widget", on_skip=skipped.append)

    assert relpaths(hits) == ["small.md"]
    assert len(skipped) == 1
    assert "huge.md" in skipped[0]
    # ... but the same file is still listable and readable: no cap there.
    assert search.relpath_for(tmp_path, fat) == "huge.md"
    assert search.load_note(tmp_path, "huge.md").startswith("widget")


def test_unreadable_files_are_skipped_not_fatal(tmp_path, monkeypatch):
    write_notes(tmp_path, {"good.md": "widget\n", "bad.md": "widget\n"})
    real_read = search.read_note_text

    def explode(path):
        if path.name == "bad.md":
            raise PermissionError("nope")
        return real_read(path)

    monkeypatch.setattr(search, "read_note_text", explode)

    skipped: list[str] = []
    hits = search.search_notes(tmp_path, "widget", on_skip=skipped.append)

    assert relpaths(hits) == ["good.md"]
    assert skipped and "bad.md" in skipped[0]


# --------------------------------------------------------------------------- #
# Formatted output (what the model actually sees)
# --------------------------------------------------------------------------- #


def test_formatted_results_carry_relpath_uri_score_and_lines():
    hits = search.search_notes(FIXTURE_NOTES, "widget")
    text = search.format_search_results("widget", hits)

    assert 'Found 3 note(s) matching "widget":' in text
    for hit in hits:
        assert hit.relpath in text
        assert hit.uri in text
        assert str(hit.score) in text
    assert "> The widget is the unit of work here." in text
    assert "read_note" in text  # tells the model how to follow up
    # Ordering survives formatting.
    assert text.index("alpha.md") < text.index("beta.md") < text.index("gamma.md")


def test_search_notes_tool_returns_formatted_text(notes_server):
    text = server.search_notes("widget")

    assert text == search.format_search_results(
        "widget", search.search_notes(FIXTURE_NOTES, "widget")
    )
    assert "notes:///alpha.md" in text


def test_search_notes_tool_passes_max_results_through(notes_server):
    text = server.search_notes("widget", max_results=1)

    assert 'Found 1 note(s) matching "widget":' in text
    assert "alpha.md" in text
    assert "beta.md" not in text


def test_search_notes_tool_says_so_when_nothing_matches(notes_server):
    assert server.search_notes("zzznotfound").startswith('No notes matched "zzznotfound".')
