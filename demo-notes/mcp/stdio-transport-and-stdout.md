---
title: stdio transport and the stdout rule
tags: [mcp, protocol, debugging]
updated: 2026-07-11
---

# stdio transport and the stdout rule

A local MCP server does not listen on a port. The client launches it as a child process and
speaks JSON-RPC over the pipe. That is the whole transport.

```
client process
   │  spawns
   ▼
server process
   stdin  ← JSON-RPC requests
   stdout → JSON-RPC responses
   stderr → logs, for humans
```

## The one rule

**stdout belongs to the protocol.** Every byte you write there must be a valid JSON-RPC
message. One stray `print("loaded 42 notes")` and the client sees a parse error, usually
reported as something unhelpful like "server disconnected".

Everything a human should read goes to stderr:

```python
import sys
print(f"scanned {count} files", file=sys.stderr)
```

This bit me for twenty minutes on my first server. The fix was one keyword argument. The
lesson generalises: on stdio, logging is a side channel, not the main channel.

## Consequences worth knowing

- **Startup errors are cheap.** If configuration is missing, write to stderr and exit
  non-zero. The client shows the exit status, and you get a real error instead of a hang.
- **The process is single-tenant.** One client, one server process, one folder. No auth
  story is needed because the OS process boundary *is* the auth story.
- **Environment variables are the config surface.** The client passes them in the launch
  spec, so `NOTES_DIR=/path/to/notes` is the whole configuration API.
- **The interpreter path is the #1 footgun.** `"command": "python"` resolves against the
  client's PATH, not your shell's. Point it at the virtualenv interpreter explicitly.

## When to reach for HTTP instead

Remote or multi-user servers use a streamable HTTP transport, which brings sessions, auth
and deployment along with it. For a personal server reading a local folder, stdio is
strictly less work and strictly more private — nothing leaves the machine.

## See also

- [[debugging-with-mcp-inspector]] — how I test the handshake without a real client.
- [[building-a-notes-server]] — where I actually tripped over this.
- [[MCP resources vs tools]] — what rides on top of the transport.
