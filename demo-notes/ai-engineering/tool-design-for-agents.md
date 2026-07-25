---
title: Tool design for agents
tags: [ai-engineering, agents, api-design]
updated: 2026-07-17
---

# Tool design for agents

A tool definition is a prompt. The name, the argument names, the docstring and the error
strings are all read by a model that has no other information about your system. Treat them
with the care you would give a public API, because that is what they are.

## What I check before shipping a tool

- **Name is a verb phrase.** `search_notes`, not `notes_search_handler`. The model matches on
  intent, and intent is a verb.
- **The docstring says when to use it, not just what it does.** The useful sentence is
  usually the second one: *"Use this first to find relevant notes, then read the full note if
  more context is needed."* That sentence is what produces a sane call sequence.
- **Arguments are few and flat.** Two or three scalars. Deeply nested objects invite
  malformed calls.
- **Defaults are sensible.** `max_results: int = 5` means the model can call it with just a
  query, which it will.
- **Output is written for a reader, not a parser.** Formatted text with the identifiers the
  model needs to make the follow-up call. Returning raw JSON to a language model is a habit
  from a different era.
- **Errors teach.** "No notes matched 'foo' — try a broader term" is a repair instruction.
  "KeyError: 'foo'" is a dead end.

## Failure modes

**Too many tools.** Past roughly a dozen the model starts picking by vibe. Consolidate, or
gate them behind context.

**Overlapping tools.** If two descriptions could plausibly answer the same request, the model
will pick inconsistently and you will blame the model.

**Chatty tools.** A tool that returns two thousand lines has spent someone else's context
budget ([[context-engineering]]). Truncate, and say that you truncated.

**Silent clamping.** Clamp `max_results` to a sane range, but mention it in the output so the
model is not confused about why it got five results after asking for five hundred.

## The bit that surprised me

Improving a docstring moved behaviour more reliably than any change to the system prompt.
The tool description is the highest-leverage text in an agent, because it is read exactly at
the moment of decision. Which makes it a variable worth measuring — see [[evals-first]].

## See also

- [[MCP resources vs tools]] — tools are the model-controlled half of the protocol.
- [[building-a-notes-server]] — three tools, one of which does real work.
