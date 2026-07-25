---
title: Debugging with MCP Inspector
tags: [mcp, debugging, workflow]
updated: 2026-07-12
---

# Debugging with MCP Inspector

The Inspector is a local web UI that speaks the protocol at your server so you do not have
to guess what a chat client is doing on your behalf. It is the fastest feedback loop I have
found for this kind of server.

```
npx @modelcontextprotocol/inspector
```

Point it at the same launch command the real client would use, including the environment
variables, and step through by hand.

## My checklist

1. **Does it connect?** If not, it is almost always the interpreter path or a crash during
   startup. Read stderr first — see [[stdio-transport-and-stdout]].
2. **Does the tool list look right?** Names, descriptions, argument schemas. If a description
   reads badly to me, it will read badly to the model too ([[tool-design-for-agents]]).
3. **Does the listing enumerate everything?** For a folder-backed server, count the files on
   disk and compare. Hidden directories should be absent.
4. **Does a read round-trip?** Pick an entry with an awkward filename — spaces, an accent,
   an uppercase letter — and fetch it. This is where URI encoding bugs surface.
5. **One adversarial probe.** Ask for `../../etc/passwd` by hand. It must come back as a
   clean refusal, not a traceback and not file contents.

## Why the automated test still matters

The Inspector proves the server works *right now, for me, by hand*. A subprocess test that
launches the server over stdio with the SDK's own client and asserts the handshake proves it
still works next month. Once that test exists, the Inspector pass becomes a formality rather
than the first real check — which is the same argument as [[evals-first]], applied to a
protocol instead of a model.

## See also

- [[building-a-notes-server]]
- [[MCP resources vs tools]]
