---
title: Build log — a notes server over my vault
tags: [mcp, build-log, python]
updated: 2026-07-16
---

# Build log — a notes server over my vault

Goal for the evening: expose a folder of markdown to any MCP client, read-only, in as few
lines as I can defend. Ended at roughly 130 lines plus tests.

## Design in three bullets

- One search tool (`search_notes`), plus two thin ones (`list_notes`, `read_note`).
- One resource per markdown file, URI `notes:///<relative path>`.
- Zero writes. The server cannot modify or delete anything, by construction.

## Things that cost me time

**1. Three slashes, not two.** `notes://My Note.md` parses the first segment as a URL
authority, and a hostname may not contain a space — so the URL type rejects it outright. In
the three-slash form the authority is empty and the whole relative path lands in the path
component, where percent-encoding handles spaces, Unicode and nesting uniformly. My vault is
full of filenames with spaces, so this was not a theoretical problem.

**2. Templates do not match nested paths.** My first attempt registered a URI template with
a `{path}` parameter. A template parameter compiles to a pattern that stops at `/`, so
`mcp/inbox.md` never matched — and templates are advertised on a different list endpoint
anyway, so the plain listing came back empty. Scanning the folder at startup and registering
one concrete resource per file is both simpler and correct.

**3. Decode before you join.** The containment check has to run on the *decoded* path.
Resolve, then verify with `is_relative_to` against the resolved notes directory. `..`
segments and absolute paths get rejected with a clean message. This is the only security
property the server has, so it gets its own test file.

## Scoring, deliberately dumb

Case-insensitive. Split the query into words, count occurrences, add a small bonus for the
intact phrase, break ties on relative path so output is stable. No stemming, no embeddings,
no vector store. It is a folder of notes, not a search company — see
[[context-engineering]] for why I stopped reaching for retrieval machinery by reflex.

## What I would add next

- Backlinks. The vault is full of `[[wikilinks]]` and nothing reads them yet.
- A prompt primitive, so the project demonstrates all three halves of the protocol.
- Word-boundary matching, because "art" currently matches "start".

## See also

- [[MCP resources vs tools]] — the distinction this server exists to demonstrate.
- [[stdio-transport-and-stdout]] — the transport, and the print statement that broke it.
- [[evals-first]] — the integration test I should have written before the features.
- [[Start Here]] — back to the index.
