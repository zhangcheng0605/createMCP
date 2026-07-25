---
title: MCP resources vs tools
tags: [mcp, protocol, concepts]
updated: 2026-07-14
---

# MCP resources vs tools

This is the note I wish I had read on day one. The whole question of MCP resources vs tools
comes down to one line: **resources are nouns, tools are verbs.**

## The one-line version

- **Resources** are addressable content the client can fetch. Data at rest. A file, a table,
  a config blob, a wiki page. Each resource has a URI, a name, and a MIME type.
- **Tools** are functions the model can call, with typed arguments and side effects allowed.
  Search, create ticket, run query, send email.

If you can point at it, it is a resource. If you can do it, it is a tool.

## Why the distinction exists at all

The two halves of the protocol have different *control models*, and that is the real reason
they are separate primitives:

| | resources | tools |
|---|---|---|
| controlled by | the application / the user | the model |
| shape of the call | `resources/list`, `resources/read` | `tools/list`, `tools/call` |
| identified by | a URI | a name + JSON schema |
| side effects | none, read-only by convention | allowed, and expected |
| discovery | enumerate and attach | model reads the docstring and decides |

Resources are **application-controlled**: the host app decides what to put in front of the
model, often by asking the human. Tools are **model-controlled**: the model reads the tool
list and picks. Prompts, the third primitive, are **user-controlled** — a human invokes them
deliberately.

So "MCP resources vs tools" is not really a question about data formats. It is a question
about *who is allowed to decide* that this content enters the context window.

## The trap I fell into

I built my first server with search exposed as a resource — something like
`search:///query/mcp`. It technically worked, and it was wrong. Resources are meant to be
enumerable and stable; a search result set is neither. The moment I flipped search to a tool
and left the notes as resources, everything got simpler: the resource list became a boring
mirror of the folder, and the interesting logic lived in one tool.

Rule of thumb I now use: **if you would struggle to write a `resources/list` for it, it is
not a resource.**

## The asymmetry nobody warns you about

Clients support the two primitives unevenly. Tools are supported everywhere, because tools
are what make an agent useful. Resources are surfaced inconsistently — some clients let the
model follow a resource URI on its own, and some only expose resources as something the
human manually attaches to the conversation.

Practical consequence, learned the hard way in [[building-a-notes-server]]: if the model
must be able to read your content unattended, also expose a thin tool that reads it. Not
because resources are broken, but because tools are the half of the protocol with universal
support. My notes server therefore has `read_note` *and* `notes:///` resources, and both
return the same bytes.

## How I explain it to people now

> The server hands the client a filing cabinet (resources) and a set of power tools
> (tools). The human decides which drawer to open. The model decides which tool to pick up.

## See also

- [[tool-design-for-agents]] — once you know something is a tool, the docstring is the API.
- [[building-a-notes-server]] — this distinction, implemented in about 130 lines.
- [[stdio-transport-and-stdout]] — the transport underneath both halves.
