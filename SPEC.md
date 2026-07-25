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
reading their real notes, and post it on LinkedIn. Code clarity matters more than cleverness —
every non-obvious block should be understandable by an MCP beginner reading the source.

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
├── pyproject.toml       # project metadata + deps (mcp SDK, pytest)
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

## 4. Configuration

- The notes folder is provided via the **`NOTES_DIR` environment variable**.
- On startup: resolve it to an absolute real path (`Path(...).resolve()`). If unset or not an
  existing directory, print a clear error to **stderr** and exit non-zero.
  (Never print to stdout outside the protocol — stdio transport uses stdout for JSON-RPC;
  stray prints corrupt the stream. All logging goes to stderr.)
- Only files matching `*.md` (recursive) are in scope. Skip hidden directories (any path
  segment starting with `.`, e.g. `.obsidian/`, `.git/`).

## 5. Resources (the nouns)

**URI scheme:** `notes://{relpath}` where `relpath` is the path relative to `NOTES_DIR`,
using forward slashes. Example: `notes://business/pricing.md`.

**Listing.** The server must answer `resources/list` with one entry per markdown file:
- `uri`: as above
- `name`: the file's relative path (or the first `# heading` in the file if trivially cheap —
  optional, don't over-engineer)
- `mimeType`: `text/markdown`

Implementation note: FastMCP registers resources declaratively; for a dynamic folder, scan
`NOTES_DIR` and register each file's resource at startup, OR use a resource template
(`notes://{path}`) plus explicit list support — whichever the current SDK version supports
most simply. Check the SDK's docs/examples rather than assuming; this is the one part of the
project where API details drift.

**Reading.** Given `notes://{relpath}`, return the file's full text (UTF-8, `errors="replace"`).

**Security invariant (must have a test):** before reading, resolve the requested path and
verify it is inside the resolved `NOTES_DIR` (`Path.is_relative_to`). Reject anything else —
`..` segments, absolute paths, symlinks escaping the folder — with a clean error, not a stack
trace. The same check applies to any path handling in the search tool.

## 6. Tools (the verbs)

### 6.1 `search_notes` (required)

```python
def search_notes(query: str, max_results: int = 5) -> str
```

Docstring (the model reads this to decide when to call — keep it close to this):
> Search all markdown notes for a text query. Returns the best-matching notes with the
> matching lines and their resource URIs. Use this first to find relevant notes, then read
> the full note via its resource URI if more context is needed.

Behavior:
- Case-insensitive matching. Split the query into words; a file scores by total number of
  word occurrences, with a small bonus for the full phrase appearing intact. Deliberately
  simple — no stemming, no fuzz.
- For each of the top `max_results` files return: the `notes://` URI, the match count, and
  up to 3 matching lines (trimmed, max ~150 chars each).
- Return results as readable formatted text (not JSON) — the consumer is a language model.
- Empty/whitespace query → friendly message, not an error. No matches → say so and suggest
  broader terms. Clamp `max_results` to 1–20.
- Read files lazily and skip unreadable ones (log to stderr, continue). Skip files > 2 MB.

### 6.2 `list_notes` (required, tiny)

```python
def list_notes() -> str
```
Returns a formatted tree/list of all note URIs with file sizes and modified dates. Exists
because some clients surface resources poorly; this guarantees the model can always discover
what's available through a tool. (Also a nice talking point: same data as `resources/list`,
exposed on both halves of the protocol.)

## 7. Server wiring

- `server.py` creates `FastMCP("notes-mcp")`, registers the two tools and the resources,
  and runs with stdio transport when executed as a script.
- Provide a console entry point in `pyproject.toml` (e.g. `notes-mcp = "notes_mcp.server:main"`).
- `search.py` contains the scanning/scoring functions as pure functions taking
  `(notes_dir: Path, query: str, ...)` — importable and testable without any MCP machinery.

## 8. Tests (pytest, must pass)

1. **Search:** finds a known term in fixtures; ranks the file with more hits first; phrase
   bonus works; empty query handled; `max_results` respected/clamped.
2. **Security:** `notes://../secret.md`, absolute-path URIs, and a symlink pointing outside
   the fixtures folder are all rejected. (Create the symlink inside the test; skip on
   platforms where symlink creation fails.)
3. **Scanning:** hidden dirs skipped; non-`.md` files ignored; nested folders found.
4. **Smoke:** the FastMCP app object exposes exactly the expected tool names.

Manual verification (document in README, don't automate): run
`npx @modelcontextprotocol/inspector` against the server, confirm tools and resources appear
and both tools return sensible output against a real folder.

## 9. Client registration (must be in README, verified working)

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
  reader who has never seen MCP).
- Install, configure, register (both clients), and test instructions that actually work.
- A "Try asking Claude" section with 3 example prompts, e.g. *"What have I written about X?
  Search my notes."*
- Placeholder slot for a demo GIF.

## 11. Definition of done

- [ ] `pytest` green.
- [ ] Server starts and lists tools/resources in MCP Inspector.
- [ ] Registered in Claude Code in-session (`claude mcp add`), and a live query like
      *"search my notes for mcp"* round-trips: model calls `search_notes`, then reads a
      resource, then answers from it.
- [ ] Path-traversal attempts rejected (tests + one manual probe via Inspector).
- [ ] README complete per §10.

## 12. Stretch goals (only if asked)

1. `get_backlinks(note)` tool — find notes containing `[[wikilinks]]` to a given note
   (Obsidian flavor).
2. Word-boundary matching + simple TF-IDF-ish weighting in search.
3. An MCP **prompt** (`summarize_note`) so the project demonstrates all three MCP
   primitives — tools, resources, prompts.
