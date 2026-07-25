# notes-mcp

A small, read-only [MCP](https://modelcontextprotocol.io) server that hands a folder of
markdown notes to an MCP client such as Claude Code or Claude Desktop. Point `NOTES_DIR` at a
notes folder (an Obsidian vault works fine) and the server registers one resource per `.md`
file plus three tools — `search_notes`, `list_notes`, `read_note` — so the model can find a
note by keyword and then read it in full. It is an evening learning project, not a product:
~200 lines of MCP wiring plus ~350 lines of plain-Python search, no writes, no embeddings, no
network. I built it mostly to understand the difference between MCP **tools** and
**resources**, and the notes below are what I actually learned doing it.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│ MCP client                                               │
│ (Claude Code / Claude Desktop / MCP Inspector)           │
└───────────┬──────────────────────────────────────────────┘
            │  spawned as a child process; JSON-RPC over pipes
            │    stdin → requests   stdout → responses   stderr → logs
┌───────────▼──────────────────────────────────────────────┐
│ notes-mcp   —  python -m notes_mcp.server                │
│                                                          │
│ server.py   FastMCP("notes-mcp")                         │
│   tools     search_notes / list_notes / read_note        │
│   resources one per .md file, registered at startup      │
│                                                          │
│ search.py   scan / score / snippet / containment         │
│             (pure functions, no MCP imports)             │
└───────────┬──────────────────────────────────────────────┘
            │  read-only, and never outside this folder
┌───────────▼──────────────────────────────────────────────┐
│ $NOTES_DIR                                               │
│   Start Here.md                                          │
│   mcp/MCP resources vs tools.md                          │
│   reading-log/book-notes/…                               │
│   (.obsidian/, .git/ and other dotted paths skipped)     │
└──────────────────────────────────────────────────────────┘
```

A resource URI is the relative path, percent-encoded, behind three slashes:
`notes:///mcp/MCP%20resources%20vs%20tools.md`.

Everything is resolved at startup: `main()` reads `NOTES_DIR`, scans it once, registers the
resources, then blocks on stdio. Notes added later show up on the next restart.

## Tools vs Resources — what I learned

MCP gives a server two different ways to put content in front of a model, and the split is
about *who decides*, not about data formats. **Resources are nouns** — addressable content with
a URI that the client can list (`resources/list`) and fetch (`resources/read`); here that is
one entry per markdown file, so the notes themselves are resources. **Tools are verbs** —
functions with typed arguments that the model chooses to call after reading their docstrings;
searching is a verb, so `search_notes` is a tool. The catch that made this project interesting
is that client support is not symmetric: Claude Code can follow a `notes:///…` URI on its own
after a search, whereas Claude Desktop has historically surfaced resources only through manual
attachment by the human, so a model there can list notes but not open one. That is why the
tiny `read_note` and `list_notes` tools exist alongside the resources — they expose the same
data on the model-controlled half of the protocol, so the search-then-read loop works in any
client rather than only in the one I happened to test first.

## Install

Requires Python 3.10+ (built on 3.11).

```bash
git clone <this repo> createMCP
cd createMCP
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Tested against **`mcp` SDK version 1.28.1** (the declared dependency is `mcp>=1.0`). If a later
SDK changes URI parsing or the FastMCP resource API, that is the version things were verified
on.

There is deliberately **no console script**. The one launch command, everywhere, is
`python -m notes_mcp.server`.

## Configure

The notes folder comes from the `NOTES_DIR` environment variable. Nothing else is configurable.

```bash
NOTES_DIR=./demo-notes .venv/bin/python -m notes_mcp.server
```

That starts the server and blocks, waiting for JSON-RPC on stdin — a client normally does the
launching. On startup it writes one line to **stderr** and nothing at all to stdout:

```
notes-mcp: serving 11 note(s) from /path/to/createMCP/demo-notes over stdio
```

If `NOTES_DIR` is unset, or is not an existing directory, it prints a one-line explanation to
stderr and exits `1` — no traceback. Only `*.md` files are in scope, recursively; any path
segment starting with `.` is skipped, so `.obsidian/` and `.git/` never appear.

## Register with a client

Both snippets need the **absolute path to this venv's interpreter**, because that is the
interpreter with `mcp` and `notes_mcp` installed. Replace
`/absolute/path/to/createMCP/.venv/bin/python` with your own path (`.venv/bin/python -c
'import sys; print(sys.executable)'` prints it).

**Claude Code:**

```bash
claude mcp add notes \
  -e NOTES_DIR=/path/to/your/notes \
  -- /absolute/path/to/createMCP/.venv/bin/python -m notes_mcp.server
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "notes": {
      "command": "/absolute/path/to/createMCP/.venv/bin/python",
      "args": ["-m", "notes_mcp.server"],
      "env": { "NOTES_DIR": "/path/to/your/notes" }
    }
  }
}
```

> **Adjust `python` to your venv's interpreter path.** This is the single most common way to
> break a local MCP server. A bare `"python"` resolves against the client's `PATH`, not your
> shell's, and Claude Desktop in particular is not launched from your shell — it will usually
> find a system Python that has never heard of `mcp`, and the only symptom is "server
> disconnected". Use the full path. (If you skipped `pip install -e .`, you also need
> `"PYTHONPATH": "/absolute/path/to/createMCP/src"` in `env`.)

To check the wiring before involving a chat client, use the Inspector:

```bash
npx @modelcontextprotocol/inspector \
  -e NOTES_DIR=/absolute/path/to/createMCP/demo-notes \
  /absolute/path/to/createMCP/.venv/bin/python -m notes_mcp.server
```

(`NOTES_DIR` can also be typed into the Inspector's Environment Variables panel before you hit
Connect.) Three tools should be listed, one resource per note, and a hand-typed
`read_note(path="../../etc/passwd")` should come back as a polite refusal rather than a
stack trace. Also worth clicking: a resource with a space in its name, which is where URI
encoding bugs surface.

### Or check it without leaving the terminal

The Inspector also has a `--cli` mode, which is the quickest possible answer to "does this thing
work at all" — no browser, no chat client. Run these from the repo root:

```bash
# 1. What tools does the server expose?
npx -y @modelcontextprotocol/inspector --cli \
  -e NOTES_DIR=demo-notes .venv/bin/python -m notes_mcp.server \
  --method tools/list

# 2. What resources? (one per note, percent-encoded URIs)
npx -y @modelcontextprotocol/inspector --cli \
  -e NOTES_DIR=demo-notes .venv/bin/python -m notes_mcp.server \
  --method resources/list

# 3. Actually search the notes
npx -y @modelcontextprotocol/inspector --cli \
  -e NOTES_DIR=demo-notes .venv/bin/python -m notes_mcp.server \
  --method tools/call --tool-name search_notes --tool-arg query="stdout JSON-RPC"

# 4. Read one note back by its URI
npx -y @modelcontextprotocol/inspector --cli \
  -e NOTES_DIR=demo-notes .venv/bin/python -m notes_mcp.server \
  --method resources/read --uri "notes:///mcp/stdio-transport-and-stdout.md"

# 5. Confirm the boundary holds
npx -y @modelcontextprotocol/inspector --cli \
  -e NOTES_DIR=demo-notes .venv/bin/python -m notes_mcp.server \
  --method tools/call --tool-name read_note --tool-arg path="../../etc/passwd"
```

Step 3 is the interesting one: `mcp/stdio-transport-and-stdout.md` should come back ranked first
by a wide margin, with the notes that merely `[[wikilink]]` to it scoring 1 each. Step 5 should
return `isError: false` with the text `Cannot read that note: ... is outside the notes folder.` —
a refusal is a normal answer here, not a protocol error.

## Remote / hosted (a URL you can paste into a client)

Everything above launches the server as a child process over **stdio**. Some clients instead ask
for a **remote MCP server URL** — Claude's "Add custom connector" dialog, for instance. Same
tools, same resources, different transport:

```bash
MCP_TRANSPORT=http NOTES_URL_SECRET=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))') \
  NOTES_DIR=./demo-notes .venv/bin/python -m notes_mcp.server
```

The endpoint is `/mcp` (or `/mcp/<secret>`, below); `/healthz` is always open for platform health
checks.

### Read this before you host your notes

**Going from stdio to HTTP moves the security boundary.** On stdio the only thing that can talk
to the server is the process that spawned it, which is why no auth is needed. On HTTP, whatever
check the server performs is the *only* thing between your notes and the internet. So it refuses
to start over HTTP unless you pick one of three modes:

| Env var | What it does | Use when |
| --- | --- | --- |
| `NOTES_TOKEN` | Requires `Authorization: Bearer <token>` | The client can send a header. Strongest. |
| `NOTES_URL_SECRET` | Serves at `/mcp/<secret>` — the URL *is* the credential | The client only accepts a URL |
| `ALLOW_NO_AUTH=1` | No protection whatsoever | Only for notes you would publish anyway |

Set `NOTES_TOKEN` and `NOTES_URL_SECRET` together and a caller needs both the right path and the
right header.

**The catch with URL-only clients.** A connector dialog that offers a URL plus optional OAuth has
nowhere to put a bearer token, and this server does not implement OAuth (that means running an
authorisation server — a much bigger project than this one). So for that dialog your realistic
options are `NOTES_URL_SECRET` or `ALLOW_NO_AUTH=1`. A secret in the path is genuinely weaker
than a header — URLs get logged by proxies, saved in browser history, and pasted into the wrong
window — so treat the entire URL as a password.

**And the notes have to live on the host.** The server reads the filesystem it runs on, so
hosting it means copying those notes to that machine. For a personal vault that is usually the
wrong trade, and local stdio is the better answer. Host the curated `demo-notes/` instead, or a
folder you would be comfortable publishing.

### Deploying it

A `Dockerfile` and a `render.yaml` are included. On [Render](https://render.com): New → Blueprint,
point it at this repo, deploy. The blueprint generates `NOTES_URL_SECRET` for you — read it from
the service's **Environment** tab afterwards, then give your client:

```
https://<your-service>.onrender.com/mcp/<the-generated-secret>
```

Any container host works the same way (Fly, Railway, Cloud Run); they all inject `PORT`, which the
server honours. Two things to expect on a free plan: the instance sleeps when idle, so the first
request after a while is slow enough that a client handshake can time out — retry, or use a paid
plan — and the image serves `demo-notes/` unless you edit the `COPY` line in the `Dockerfile`.

> The `Dockerfile` itself has not been built and run here (no Docker daemon in the environment it
> was written in). Its two load-bearing steps *were* verified directly: `pip install ".[http]"`
> resolves in a clean virtualenv, and the `HEALTHCHECK` command returns 0 against a live server.
> Expect the image to work; do not assume it, and read the first deploy's build log.

## Try asking Claude

With `NOTES_DIR` pointed at `demo-notes/`, these three all produce a search-then-read round
trip against the sample content:

1. *"What did I write about MCP resources vs tools? Search my notes and summarise the
   distinction."* — hits `mcp/MCP resources vs tools.md` hard (the phrase bonus puts it well
   clear of everything else), then the model opens it for the control-model table.
2. *"Search my notes for stdout — why does a stray print break a local MCP server?"* — finds
   `mcp/stdio-transport-and-stdout.md` and answers from the note rather than from general
   knowledge.
3. *"Look through my reading log and tell me which papers and books I marked as keep this
   month."* — exercises a nested folder and a filename with a space
   (`reading-log/2026-07 reading log.md`), which is where URI encoding bugs would show up.

A good sanity check that it is really using the notes: ask *"list every note you can see"* and
count against the folder. `list_notes` returns all 11 demo notes with sizes and modified dates.

## Demo

Record against **`demo-notes/`**, not a personal vault:

```bash
export NOTES_DIR=/absolute/path/to/createMCP/demo-notes
```

Two reasons. Privacy — a real vault on a public recording leaks whatever happens to be in the
frame, and you cannot un-publish a video. Repeatability — the demo folder is fixed, so search
scores and result ordering are identical on every take, and a retake does not turn into a
different demo. `demo-notes/` is eleven curated notes on MCP and AI engineering, nested up to two
folders deep, three of them with spaces in the filename.

Rough shot list for the recording: `list_notes` first so the folder is visible, then one search,
then the model reading the top hit and answering from it, then the traversal probe being refused.

<!-- DEMO GIF SLOT — drop the recording in docs/demo.gif and replace the line below with:
     ![notes-mcp: searching and reading notes from Claude](docs/demo.gif) -->

> _demo GIF goes here_

## Tests

From the repo root (`pyproject.toml` sets `testpaths = ["tests"]` and `pythonpath = ["src"]`, so
this works whether or not you did the editable install):

```bash
.venv/bin/pytest
```

132 tests, ~8 seconds:

| file | tests | covers |
|---|---|---|
| `tests/test_security.py` | 41 | path traversal and containment, both layers |
| `tests/test_search.py` | 37 | scoring, phrase bonus, tie-breaks, clamping, snippets |
| `tests/test_scanning.py` | 28 | hidden dirs, non-`.md`, nesting, URI round-trips |
| `tests/test_integration.py` | 15 | live protocol conversation over stdio |
| `tests/test_smoke.py` | 11 | import with no env set, tool names, `main()` failure modes |

`tests/test_integration.py` is the one that matters most: it launches the server as a **real
subprocess** and drives it with the SDK's own client (`mcp.client.stdio.stdio_client` +
`ClientSession`) — `initialize`, `tools/list`, `resources/list`, `tools/call`, `resources/read`.
So it proves the server actually speaks MCP on the wire, rather than proving that some Python
functions return strings. It also asserts that a traversal attempt is refused over the wire (as
a normal text result, `isError` false), and that the startup banner landed on stderr with no
traceback — if anything else had reached stdout, `initialize` could not have parsed at all. With
that test green, the Inspector check is a formality rather than the first real test.

`search.py` has no MCP imports at all, which is why most of the suite is fast, ordinary unit
tests with `tmp_path`.

## Gotchas I hit

**Three slashes in the URI, not two.** `notes:///note.md`, never `notes://note.md`. In the
two-slash form the first path segment is parsed as the URL *authority* — a hostname — and a
hostname may not contain a space, so `AnyUrl("notes://My Note 2026.md")` raises a pydantic
`ValidationError` — literally *"Input should be a valid URL, invalid domain character"*. Any top-level note with a space in its
filename would take the server down at startup, and vaults are full of those. The three-slash
form leaves the authority empty and puts the whole relative path in the path component, where
percent-encoding handles spaces, Unicode and nesting uniformly. Build URIs with
`"notes:///" + quote(relpath)` and always URL-decode *before* joining and containment-checking.

**stdout belongs to the protocol.** stdio transport is JSON-RPC over the child process's pipes,
so every byte on stdout must be a valid message. One `print("loaded 42 notes")` corrupts the
stream and the client reports something unhelpful like "server disconnected". All logging goes
through a `log()` helper that writes to stderr, and one of the smoke tests asserts that
importing the module and starting the server produce **zero bytes** on stdout.

**Resource templates were the wrong tool for this.** My first attempt registered a single
template, `@mcp.resource("notes://{path}")`, which felt obviously right and failed twice over:
a `{param}` segment compiles to a pattern that does not match across `/`, so nested notes like
`mcp/inbox.md` never matched at all; and templates are advertised on
`resources/templates/list`, not `resources/list`, so a client asking for the note list got an
empty array. Scanning the folder once at startup and registering one concrete resource per file
is both simpler and correct — `list_resource_templates()` returning `[]` here is the expected
result, not a bug.

**A refusal is an answer, not an exception.** The pure layer raises (`NoteAccessError`), but the
`read_note` *tool* catches it and returns a sentence: `Cannot read that note: '../secret.md' is
outside the notes folder.` Models handle a clear sentence far better than a protocol error, and
it keeps tracebacks out of the transcript. Same reason an empty query gets a friendly nudge
instead of a validation failure.

**"Listed" and "readable" must be one rule, not two.** The scan and the read each started with
their own copy of the scope rule, and the copies drifted — twice. First a symlink pointing
outside the vault got listed by unresolved path and blew up on read, crashing startup. Then, more
subtly, the scanner checked for hidden path segments *before* resolving while the reader checked
*after*, so a innocuous-looking `link.md` pointing at `.obsidian/workspace-notes.md` published
the hidden file in `resources/list` and leaked its text through search snippets — while every
attempt to read it was refused. Both halves now call one `in_scope_relpath()` predicate, applied
to the resolved path, which decides containment, hidden segments and the `.md` suffix together.
Two rules that must agree are better written as one rule with two callers. Symlinks that alias a
note inside the folder still collapse to a single entry rather than a duplicate URI.

**Not every `resolve()` failure is an `OSError`.** A circular symlink raises `RuntimeError`, and
a path containing a NUL byte raises `ValueError` — both slipped past an `except OSError` and were
reported to the client verbatim, which disclosed the server's absolute notes path. Worse, the NUL
case was reachable from a perfectly well-formed URI (`notes:///ok%00.md`), because the percent-
decode happens before the containment check. `safe_resolve()` now funnels every failure mode into
one refusal that echoes only what the caller sent.

## Scope

Read-only by construction: there is no code path that writes, moves or deletes a file. No
embeddings or vector search — scoring is case-insensitive substring counting plus a `+2` bonus
per intact occurrence of the whole phrase (multi-word queries only), ties broken by path, which
is deterministic and
completely adequate for a few hundred notes. stdio only: no HTTP transport, no auth, no
multi-user anything. Files over 2 MB are skipped while *searching* (logged to stderr); that cap
does not apply to listing or reading.

## License

MIT, as declared in `pyproject.toml`. (No separate `LICENSE` file yet.)
