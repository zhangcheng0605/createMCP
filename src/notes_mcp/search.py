"""Scanning, scoring and path helpers for notes-mcp -- pure Python, no MCP.

Nothing in this module imports from ``mcp``, and nothing here prints or reads
global state: every function takes the notes directory as an explicit argument.
That is what makes this half of the project unit-testable on its own, and it
keeps all the protocol-shaped code in ``server.py``.

Two rules of the house live here:

1. **URI form.** A note is addressed as ``notes:///<relpath>`` -- *three*
   slashes -- see :func:`note_uri`.
2. **Containment.** Every path that comes from outside (a URI in a
   ``resources/read`` call, the ``path`` argument of the ``read_note`` tool) is
   resolved and checked against the notes directory before it is opened -- see
   :func:`resolve_note_path`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence
from urllib.parse import quote, unquote

#: Prefix of every note URI. Three slashes, not two -- see :func:`note_uri`.
URI_PREFIX = "notes:///"

#: Files larger than this are skipped *while searching* only. Listing a note,
#: reading it as a resource, and the read_note tool have no size limit.
MAX_SEARCH_FILE_BYTES = 2 * 1024 * 1024

#: How many matching lines to quote per note, and how long each may be.
MAX_LINES_PER_NOTE = 3
MAX_LINE_CHARS = 150

#: Score added for each occurrence of the query as one intact phrase.
PHRASE_BONUS = 2

#: search_notes clamps max_results into this range.
MIN_MAX_RESULTS = 1
MAX_MAX_RESULTS = 20


class NoteAccessError(Exception):
    """A requested note cannot be served: outside the notes folder, or missing.

    Raised instead of letting an ``OSError`` (or worse, a traversal read)
    happen, so callers can turn it into one clean sentence for the model.
    """


@dataclass
class SearchHit:
    """One note that matched a search, with the lines that matched."""

    relpath: str  # path relative to the notes dir, forward slashes
    uri: str  # notes:///... form of the same note
    score: int  # word occurrences + phrase bonus
    lines: list[str]  # up to MAX_LINES_PER_NOTE trimmed matching lines


# --------------------------------------------------------------------------- #
# URIs
# --------------------------------------------------------------------------- #


def note_uri(relpath: str) -> str:
    """Build the resource URI for a note, given its path relative to NOTES_DIR.

    ``business/pricing.md`` -> ``notes:///business/pricing.md``

    The three slashes are load-bearing. In the two-slash form
    ``notes://business/pricing.md`` a URL parser reads ``business`` as the
    *authority* (host) of the URL, and a host may not contain spaces: building
    ``notes://My Note 2026.md`` raises a validation error, which would crash the
    server on any top-level note whose filename has a space in it (Obsidian
    vaults are full of them). With three slashes the authority is empty and the
    whole relative path lands in the URL *path* component, which happily
    carries percent-encoded spaces, Unicode and nested folders. Do not
    "simplify" this to two slashes.
    """
    # quote() leaves "/" alone by default, so folder separators survive.
    return URI_PREFIX + quote(relpath)


def relpath_from_uri(uri_or_path: str) -> str:
    """Turn a note URI *or* a plain relative path into a relative path.

    Accepts ``notes:///a/b.md``, the sloppier ``notes://a/b.md`` that a model
    may produce, and a bare ``a/b.md``. Percent-escapes are decoded **here**,
    before the result is ever joined with the notes directory, so that the
    containment check in :func:`resolve_note_path` sees the real path and not an
    encoded one like ``..%2Fsecret.md``.
    """
    text = uri_or_path.strip()
    if text.lower().startswith("notes://"):
        text = text[len("notes://") :]
        text = unquote(text)
        # Drop exactly the one slash of the three-slash form. Dropping *all*
        # leading slashes would quietly turn "/etc/passwd" into "etc/passwd";
        # we would rather keep it absolute and let the containment check
        # reject it out loud.
        if text.startswith("/"):
            text = text[1:]
    return text


# --------------------------------------------------------------------------- #
# Scanning
# --------------------------------------------------------------------------- #


def safe_resolve(path: Path) -> Path | None:
    """``Path.resolve()`` that answers ``None`` instead of raising.

    ``resolve()`` has three failure modes that are *not* ``OSError`` and so slip
    past a naive ``except OSError``: a circular symlink raises ``RuntimeError``
    ("Symlink loop from ..."), an embedded NUL byte raises ``ValueError``, and
    some platforms surface odd names as ``OSError``. Every caller here wants the
    same answer -- "this is not a usable path" -- so the messy part lives in one
    place. Note the raised message is deliberately never propagated: it contains
    the server's absolute path, which callers must not learn.
    """
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def in_scope_relpath(base: Path, resolved: Path) -> str | None:
    """The scope rule for the whole server, in one place.

    Returns the note's path relative to ``base`` if it is servable, else
    ``None``. Servable means: inside ``base`` once symlinks are followed, no path
    segment starting with a dot (skipping ``.obsidian/``, ``.git/``, ``.trash/``
    and hidden files), and a ``.md`` suffix ignoring case.

    Both halves of the protocol call this -- the scanner that *advertises* notes
    and the reader that *serves* them. That is the point: when those two rules
    were written separately they drifted, and a file symlink pointing into
    ``.obsidian/`` ended up listed in ``resources/list`` but refused by every
    read. One predicate, checked against the resolved path, cannot drift.
    """
    if not resolved.is_relative_to(base):
        return None
    relative = resolved.relative_to(base)
    if any(part.startswith(".") for part in relative.parts):
        return None
    if resolved.suffix.lower() != ".md":
        return None
    return relative.as_posix()


def iter_note_files(notes_dir: Path) -> Iterator[Path]:
    """Yield every in-scope note under ``notes_dir``, sorted by relative path.

    Scope is decided by :func:`in_scope_relpath`, the same predicate the reader
    uses. Sorted so that listings and search tie-breaks are deterministic for
    tests and for the demo recording.

    Containment matters here as much as it does in :func:`resolve_note_path`: a
    symlink pointing out of the notes folder must not be *advertised* either, or
    the scanner would offer notes that every read then refuses. Entries are keyed
    by resolved relative path, so two names for one file (a symlink to a note
    next door) collapse into a single URI instead of a duplicate.

    ``rglob("*")`` rather than ``rglob("*.md")`` on purpose: the suffix test in
    :func:`in_scope_relpath` ignores case, so ``NOTES.MD`` is listed as well as
    readable. Globbing for ``*.md`` would match it on a case-insensitive
    filesystem (macOS) and miss it on a case-sensitive one (Linux) -- the kind of
    difference that turns into a bug report from one user and not another.
    """
    base = Path(notes_dir).resolve()
    candidates: dict[str, Path] = {}
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        resolved = safe_resolve(path)
        if resolved is None:
            continue
        relpath = in_scope_relpath(base, resolved)
        if relpath is None:
            continue
        candidates.setdefault(relpath, resolved)
    for relpath in sorted(candidates):
        yield candidates[relpath]


def find_note_files(notes_dir: Path) -> list[Path]:
    """List form of :func:`iter_note_files`."""
    return list(iter_note_files(notes_dir))


def relpath_for(notes_dir: Path, path: Path) -> str:
    """Path of ``path`` relative to ``notes_dir``, with forward slashes."""
    base = Path(notes_dir).resolve()
    return Path(path).resolve().relative_to(base).as_posix()


# --------------------------------------------------------------------------- #
# Reading (with the containment check)
# --------------------------------------------------------------------------- #


def resolve_note_path(notes_dir: Path, uri_or_path: str) -> Path:
    """Resolve a client-supplied note reference to a real file inside the vault.

    This is the only door into the filesystem, and it is the security boundary
    of the whole server. Both ``Path.resolve()`` calls matter: resolving
    collapses ``..`` segments and follows symlinks, so a symlink pointing out of
    the notes folder is judged by where it actually lands. ``is_relative_to``
    then rejects anything outside. Note that ``base / "/etc/passwd"`` is simply
    ``/etc/passwd`` in pathlib -- an absolute input silently replaces the base,
    which is exactly why the check below is not optional.

    Raises :class:`NoteAccessError` (never a bare OSError, never a traceback,
    never a ``RuntimeError`` from a symlink loop) for traversal attempts,
    absolute paths, unusable paths, missing files and non-markdown files.
    """
    relpath = relpath_from_uri(uri_or_path)
    if not relpath:
        raise NoteAccessError("no note path was given")
    # A NUL byte reaches here from a perfectly well-formed URI, because
    # relpath_from_uri percent-decodes "notes:///ok%00.md" first. Rejected up
    # front so the reason is specific rather than "not usable".
    if "\x00" in relpath:
        raise NoteAccessError(f"{uri_or_path!r} is not a valid note path")

    base = Path(notes_dir).resolve()
    candidate = safe_resolve(base / relpath)
    if candidate is None:
        # Circular symlink or similar. The underlying message names the server's
        # absolute path, so it is dropped: echo only what the caller sent.
        raise NoteAccessError(f"{uri_or_path!r} is not a usable note path")

    # The scope gate is in_scope_relpath -- the same predicate the scanner uses,
    # so "listed" and "readable" cannot disagree. The branches below only work
    # out *which* rule said no, to give the model a useful sentence.
    if in_scope_relpath(base, candidate) is None:
        if not candidate.is_relative_to(base):
            raise NoteAccessError(f"{uri_or_path!r} is outside the notes folder")
        if any(part.startswith(".") for part in candidate.relative_to(base).parts):
            raise NoteAccessError(f"{uri_or_path!r} is inside a hidden file or folder")
        raise NoteAccessError(f"{uri_or_path!r} is not a markdown (.md) note")

    if not candidate.is_file():
        raise NoteAccessError(f"there is no note at {relpath!r}")
    return candidate


def read_note_text(path: Path) -> str:
    """Read a file as UTF-8, replacing undecodable bytes instead of raising.

    Real note folders contain the odd file saved in another encoding; a broken
    byte should cost one character, not the whole request.
    """
    return Path(path).read_text(encoding="utf-8", errors="replace")


def load_note(notes_dir: Path, uri_or_path: str) -> str:
    """Resolve a note reference (URI or relative path) and return its full text.

    The single choke point used by both the ``read_note`` tool and the
    ``resources/read`` handler, so the containment check cannot be skipped by
    accident on one of the two paths.
    """
    return read_note_text(resolve_note_path(notes_dir, uri_or_path))


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def query_words(query: str) -> list[str]:
    """Lowercased whitespace-separated words of a query (``[]`` if blank)."""
    return query.lower().split()


def clamp_max_results(max_results: int) -> int:
    """Keep a model-supplied result count inside 1..20."""
    try:
        value = int(max_results)
    except (TypeError, ValueError):
        return MIN_MAX_RESULTS
    return max(MIN_MAX_RESULTS, min(MAX_MAX_RESULTS, value))


def score_text(text: str, query: str) -> int:
    """Score one note's text against a query. Higher is better, 0 means no match.

    Total occurrences of each query word, plus :data:`PHRASE_BONUS` for every
    occurrence of the whole query intact, so a note saying "value based pricing"
    beats one that happens to use those three words pages apart.

    Deliberately simple: substring counting, case-insensitive, no stemming and
    no word boundaries ("cat" matches "catalogue"). The phrase bonus only
    applies to multi-word queries -- for a single-word query the "phrase" is the
    word itself, which the word count already covered.
    """
    haystack = text.lower()
    words = query_words(query)
    if not words:
        return 0
    score = sum(haystack.count(word) for word in words)
    if len(words) > 1:
        score += PHRASE_BONUS * haystack.count(" ".join(words))
    return score


def matching_lines(
    text: str,
    query: str,
    limit: int = MAX_LINES_PER_NOTE,
    max_chars: int = MAX_LINE_CHARS,
) -> list[str]:
    """Up to ``limit`` lines of ``text`` containing any query word, tidied up.

    Each line has its whitespace collapsed and is truncated to ``max_chars``,
    because these snippets are meant to help a model decide whether to read the
    whole note, not to reproduce it.
    """
    words = query_words(query)
    if not words:
        return []
    found: list[str] = []
    for raw_line in text.splitlines():
        lowered = raw_line.lower()
        if not any(word in lowered for word in words):
            continue
        line = " ".join(raw_line.split())
        if not line:
            continue
        if len(line) > max_chars:
            line = line[: max_chars - 3].rstrip() + "..."
        found.append(line)
        if len(found) >= limit:
            break
    return found


def search_notes(
    notes_dir: Path,
    query: str,
    max_results: int = 5,
    on_skip: Callable[[str], None] | None = None,
) -> list[SearchHit]:
    """Search every note under ``notes_dir`` and return the best hits.

    Ranked by score descending, ties broken by relative path ascending so the
    output is stable. Unreadable and oversized files are skipped rather than
    fatal: ``on_skip`` (if given) is called with a one-line explanation, which is
    how ``server.py`` gets those messages onto stderr without this module ever
    printing anything itself.
    """
    words = query_words(query)
    if not words:
        return []

    hits: list[SearchHit] = []
    for path in iter_note_files(notes_dir):
        relpath = relpath_for(notes_dir, path)
        try:
            if path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                if on_skip:
                    on_skip(f"skipping {relpath}: larger than {MAX_SEARCH_FILE_BYTES} bytes")
                continue
            text = read_note_text(path)
        except OSError as exc:
            if on_skip:
                on_skip(f"skipping {relpath}: {exc}")
            continue

        score = score_text(text, query)
        if score <= 0:
            continue
        hits.append(
            SearchHit(
                relpath=relpath,
                uri=note_uri(relpath),
                score=score,
                lines=matching_lines(text, query),
            )
        )

    hits.sort(key=lambda hit: (-hit.score, hit.relpath))
    return hits[: clamp_max_results(max_results)]


def format_search_results(query: str, hits: Sequence[SearchHit]) -> str:
    """Render search hits as plain text for a language model to read.

    Text, not JSON, on purpose: the consumer of a tool result here is a model,
    and the URIs need to be easy to copy into a follow-up read_note call.
    """
    if not hits:
        return (
            f'No notes matched "{query}". Try fewer or broader words, '
            f"or call list_notes to see what is available."
        )

    blocks = [f'Found {len(hits)} note(s) matching "{query}":', ""]
    for position, hit in enumerate(hits, start=1):
        blocks.append(f"{position}. {hit.relpath}  ({hit.score} match score)")
        blocks.append(f"   uri: {hit.uri}")
        for line in hit.lines:
            blocks.append(f"   > {line}")
        blocks.append("")
    blocks.append("Read a full note with read_note(path=\"<relative path or uri>\").")
    return "\n".join(blocks)
