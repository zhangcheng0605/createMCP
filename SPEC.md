# Spec: `notes-mcp` — Personal Knowledge-Base MCP Server

> **Instructions for the implementing agent:** Build exactly what this spec describes. It is
> deliberately scoped small — do not add features beyond the Stretch Goals section, and only
> do those if explicitly asked. When this spec and your own judgment conflict on scope, the
> spec wins. When it conflicts on MCP protocol correctness, the official MCP docs win
> (https://modelcontextprotocol.io).

## 1. What this is

A local MCP server, written in **Python** using the **official `mcp` SDK (FastMCP API)**, that
exposes a folder of markdown notes to any MCP client (Claude Desktop, Claude Code, etc.) over
**stdio transport**.

It is a learning project with a demo goal: the owner will screen-record Claude searching and
reading notes, and post it on LinkedIn. Code clarity matters more than cleverness — every
non-obvious block should be understandable by an MCP beginner reading the source.

## 2. Goals / Non-goals

**Goals**
- Demonstrate the tools-vs-resources distinction: search is a **tool** (verb), notes are
  **resources** (nouns).
- Work out of the box against any folder of `.md` files, including an Obsidian vault.
- Be safe: read-only, and unable to read anything outside the configured notes folder.
- Be small: target ~100–150 lines for the server itself.

**Non-goals**
- No writing/editing of notes (read-only server).
- No embeddings, vector DB, or semantic search (see Stretch Goals).
- No HTTP transport, no auth, no multi-user anything.
- No note-editor features (that's Obsidian's job).

## 3. Repository layout

```
createMCP/
├── SPEC.md              # this file
├── README.md            # see §10
├── pyproject.toml       # project metadata + deps
├── demo-notes/          # 8–12 curated sample .md files, safe for public screen recording
├── src/
│   └── notes_mcp/
│       ├── __init__.py
│       ├── server.py    # MCP wiring: tool + resource registration, main()
│       └── search.py    # pure search logic, no MCP imports (unit-testable)
└── tests/
    ├── test_search.py
    ├── test_security.py # path traversal cases
    └── fixtures/notes/  # a few sample .md files used by tests
```

**pyproject.toml requirements:** `requires-python = ">=3.10"`; dependency `mcp>=1.0`
(record in the README the exact version you built and tested against); `pytest` as a dev
dependency. No console entry point — the server is launched with `python -m notes_mcp.server`
everywhere (one canonical launch method; do not also add a script alias).

## 3b. Verified environment facts (mcp 1.28.1, Python 3.11)

These were confirmed empirically in this repo — treat as ground truth, do not re-derive:

- Virtualenv lives at `.venv/`; use `.venv/bin/python` and `.venv/bin/pytest` for all commands.
  (`pip install` into the system Python fails on a PyJWT conflict — use the venv.)
- `FastMCP(name)` from `mcp.server.fastmcp`; `.tool()` decorator; `.add_resource(resource)`;
  `.run(transport="stdio")`.
- `FileResource(uri=AnyUrl(...), name=..., mime_type="text/markdown", path=Path(...))` from
  `mcp.server.fastmcp.resources` — required fields are `uri` and `path`; it reads the file itself.
- `mcp.list_resources()`, `mcp.list_tools()`, `mcp.read_resource(uri)` are **async** — a test
  touching them needs `asyncio.run(...)` (or `pytest.mark.anyio`; plain `asyncio.run` is simpler).
- `list_resource_templates()` returns `[]` when only concrete resources are registered — that is
  expected and correct here.

## 4. Configuration

- The notes folder is provided via the **`NOTES_DIR` environment variable**.
- **Resolution happens inside `main()`** (or a helper `main()` calls), NOT at module import
  time — `import notes_mcp.server` must succeed with no env var set, so tests can import the
  app object. In `main()`: resolve to an absolute real path (`Path(...).resolve()`); if unset
  or not an existing directory, print a clear error to **stderr** and exit non-zero.
  (Never print to stdout outside the protocol — stdio transport uses stdout for JSON-RPC;
  stray prints corrupt the stream. All logging goes to stderr.)
- Only files matching `*.md` (recursive) are in scope. Skip hidden directories (any path
  segment starting with `.`, e.g. `.obsidian/`, `.git/`).

## 5. Resources (the nouns)

**URI scheme:** `notes:///{relpath}` — **three slashes**, where `relpath` is the path relative
to `NOTES_DIR` using forward slashes, percent-encoded with `urllib.parse.quote`.
Example: `notes:///business/pricing.md`.

> ⚠️ **The three slashes are load-bearing (verified empirically against mcp 1.28.1).** In the
> two-slash form `notes://foo.md`, the first segment is parsed as a URL *authority/host*, and
> `AnyUrl("notes://My Note 2026.md")` raises a `ValidationError` ("invalid domain character")
> — so any top-level note with a space in its filename crashes the server. Obsidian vaults are
> full of those. The three-slash form leaves the authority empty and puts the whole relative
> path in the URL *path* component, which accepts percent-encoded spaces, Unicode, uppercase,
> and nesting uniformly. Do not "simplify" this to two slashes.

**Listing.** The server must answer `resources/list` with one entry per markdown file:
- `uri`: as above
- `name`: the file's relative path
- `mimeType`: `text/markdown`

**Implementation note (important — verified against mcp 1.28.x):** do NOT use a FastMCP
resource template (`@mcp.resource("notes://{path}")`) for this. Two reasons: (a) a `{param}`
template segment compiles to a regex that does not match across `/`, so nested paths like
`business/pricing.md` never match; (b) templates are advertised via `resources/templates/list`,
not `resources/list`, so the listing requirement fails. **The correct approach: scan
`NOTES_DIR` at startup and register one concrete resource per file** (e.g. `mcp.add_resource(...)`
with a `FileResource`/`TextResource`, or a per-file closure). Startup-only scan is acceptable;
live re-scanning is out of scope.

**URI ↔ path mapping:** the SDK's URL type percent-encodes special characters (a file named
`My Note 2026.md` lists as `notes:///My%20Note%202026.md`). Build URIs with
`"notes:///" + urllib.parse.quote(relpath)`; convert back with
`urllib.parse.unquote(str(uri).removeprefix("notes:///"))` — **URL-decode before** joining with
`NOTES_DIR` and running the containment check. Never map URIs to paths by naive string-stripping.

**Reading.** Given `notes://{relpath}`, return the file's full text (UTF-8, `errors="replace"`).

**Security invariant (must have a test):** before reading, resolve the requested path and
verify it is inside the resolved `NOTES_DIR` (`Path.is_relative_to`). Reject anything else —
`..` segments, absolute paths — with a clean error, not a stack trace. The same check applies
to any path handling in the tools (§6).

## 6. Tools (the verbs)

### 6.1 `search_notes` (required)

```python
def search_notes(query: str, max_results: int = 5) -> str
```

Docstring (the model reads this to decide when to call — keep it close to this):
> Search all markdown notes for a text query. Returns the best-matching notes with the
> matching lines and their resource URIs. Use this first to find relevant notes, then read
> the full note (via `read_note` or its resource URI) if more context is needed.

Behavior:
- Case-insensitive matching. Split the query into words; a file scores by total number of
  word occurrences, **plus a bonus of +2 per intact occurrence of the full phrase, for
  multi-word queries only** — for a single-word query the "phrase" is the word itself, which
  the word count already counted, so applying the bonus there would just scale every score by
  3× and change no ranking. Ties broken by relative path, ascending (deterministic output for
  tests and the demo). Deliberately simple — no stemming, no fuzz.
- For each of the top `max_results` files return: the `notes://` URI, the relative path,
  the match count, and up to 3 matching lines (trimmed, max ~150 chars each).
- Return results as readable formatted text (not JSON) — the consumer is a language model.
- Empty/whitespace query → friendly message, not an error. No matches → say so and suggest
  broader terms. Clamp `max_results` to 1–20.
- Read files lazily and skip unreadable ones (log to stderr, continue). Skip files > 2 MB
  **during search scanning only** — the size cap does not apply to resource listing,
  resource reads, `list_notes`, or `read_note`.

### 6.2 `list_notes` (required, tiny)

```python
def list_notes() -> str
```
Returns a formatted list of all note URIs with file sizes and modified dates. Exists
because some clients surface resources poorly; this guarantees the model can always discover
what's available through a tool. (Also a nice talking point: same data as `resources/list`,
exposed on both halves of the protocol.)

### 6.3 `read_note` (required, tiny)

```python
def read_note(path: str) -> str
```
Returns the full text of one note, given either a `notes://` URI or a relative path.
Reuses the exact same decode + containment check as resource reading (§5).

Why this exists when resources already do it: **not every client lets the model fetch
resources autonomously.** Claude Code can follow a `notes://` URI on its own; Claude Desktop
historically surfaces resources only via manual attachment. `read_note` makes the
search-then-read loop work in any client, and the README should call out this asymmetry —
it's a better tools-vs-resources lesson, not a workaround to hide.

## 7. Server wiring

- `server.py` creates `FastMCP("notes-mcp")`, registers the three tools and the resources,
  and runs with stdio transport when executed via `python -m notes_mcp.server`.
- `search.py` contains the scanning/scoring functions as pure functions taking
  `(notes_dir: Path, query: str, ...)` — importable and testable without any MCP machinery.

## 8. Tests (pytest, must pass)

1. **Search:** finds a known term in fixtures; ranks the file with more hits first; phrase
   bonus works; tie-break is deterministic; empty query handled; `max_results` clamped.
2. **Security:** `notes://../secret.md` (and equivalent `..` relative paths) and
   absolute-path inputs are rejected, via both the resource path and `read_note`.
   (A symlink-escape test is optional — `Path.resolve()` routes symlinks through the same
   containment check; don't spend evening-project time on platform-conditional symlink
   setup. See Stretch Goals.)
3. **Scanning:** hidden dirs skipped; non-`.md` files ignored; nested folders found;
   URI round-trip works for a filename containing spaces.
4. **Smoke:** `import notes_mcp.server` succeeds without `NOTES_DIR` set, and the FastMCP
   app object exposes exactly the expected tool names.
5. **Live protocol integration test** (`tests/test_integration.py`) — the most valuable test
   in the suite. Launch the server as a real subprocess over stdio using the SDK's own client
   (`mcp.client.stdio.stdio_client` + `mcp.ClientSession`) with `NOTES_DIR` pointed at
   `tests/fixtures/notes`, then assert the full handshake works: `initialize`, `tools/list`
   returns the three tools, `resources/list` returns one entry per fixture note,
   `tools/call` on `search_notes` finds a known term, and `resources/read` on a listed URI
   returns that note's text. This proves the server actually speaks MCP — it is what makes
   the Inspector check a formality rather than the first real test.

## 9. Client registration (must be documented in README)

**Claude Code:**
```bash
claude mcp add notes -e NOTES_DIR=/path/to/your/notes -- python -m notes_mcp.server
```

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "notes": {
      "command": "python",
      "args": ["-m", "notes_mcp.server"],
      "env": { "NOTES_DIR": "/path/to/your/notes" }
    }
  }
}
```
(Adjust `python` to the venv's interpreter path; note this caveat in the README — it is the
#1 thing that trips people up.)

## 10. README requirements

- One-paragraph pitch + the architecture diagram (client ↔ server ↔ folder, ASCII is fine).
- A short "Tools vs Resources — what I learned" section (3–5 sentences, written for a
  reader who has never seen MCP), including the client-support asymmetry from §6.3.
- Install, configure, register (both clients), and test instructions.
- A "Try asking Claude" section with 3 example prompts, e.g. *"What have I written about X?
  Search my notes."*
- A "Demo" section: instruct recording against the **`demo-notes/` folder** (set `NOTES_DIR`
  to it), never a personal vault — real notes on a public LinkedIn recording is a privacy
  footgun, and a curated folder makes retakes repeatable. Include a placeholder slot for
  the demo GIF.
- The exact `mcp` SDK version built and tested against.

## 11. Definition of done

**Agent-verifiable (the builder's bar — all must pass before hand-off):**
- [ ] `pytest` green.
- [ ] `import notes_mcp.server` works without env vars; `python -m notes_mcp.server` with a
      valid `NOTES_DIR` starts and idles awaiting stdio input; with a bad/missing `NOTES_DIR`
      it errors to stderr and exits non-zero.
- [ ] `demo-notes/` populated with 8–12 curated markdown files on a safe, public-friendly
      topic (nested at least one folder deep, at least one filename with a space).
- [ ] README complete per §10.

**Owner-verified manually (after hand-off — the builder only documents the steps):**
- [ ] Tools and resources appear in MCP Inspector (`npx @modelcontextprotocol/inspector`);
      one manual path-traversal probe rejected.
- [ ] Registered in Claude Code; a live query like *"search my notes for mcp"* round-trips:
      model calls `search_notes`, then reads the note, then answers from it.
- [ ] Demo recording made against `demo-notes/`.

## 12. Stretch goals (only if asked)

1. `get_backlinks(note)` tool — find notes containing `[[wikilinks]]` to a given note
   (Obsidian flavor).
2. Word-boundary matching + simple TF-IDF-ish weighting in search.
3. An MCP **prompt** (`summarize_note`) so the project demonstrates all three MCP
   primitives — tools, resources, prompts.
4. ~~Symlink-escape security test~~ — **done, deliberately kept.** The builder implemented it
   and the scanner grew symlink resolve-and-dedupe machinery to match. That machinery caused a
   real bug (a non-hidden symlink into `.obsidian/` got advertised but was unreadable), now
   fixed by making the scanner and reader share one `in_scope_relpath()` predicate. Keeping it:
   rejecting symlink escapes on both the listing and reading sides is correct behavior, and the
   tests covering it are cheap to keep now that they exist.
