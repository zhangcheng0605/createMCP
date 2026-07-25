---
title: 2026-07 reading log
tags: [reading-log]
updated: 2026-07-20
---

# 2026-07 reading log

Rating scale: **keep** (I will come back to this), **skim** (one good idea), **skip**.

## Specifications and docs

**The Model Context Protocol specification** — *keep.* Reading the spec directly was worth
more than a week of blog posts. The section on the three primitives is where the noun/verb
framing in [[MCP resources vs tools]] actually comes from; I had been carrying a fuzzier
version of it around from secondhand summaries.

**The transport section, twice** — *keep.* First read: "fine, pipes." Second read, after
debugging a broken server: the stdout rule is stated plainly and I had skipped it. Notes in
[[stdio-transport-and-stdout]].

## Papers

**Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks** (Lewis et al., 2020) —
*keep.* Re-read with six years of hindsight; my notes are in
[[paper-notes-retrieval-augmented-generation]]. Holds up better as an architecture argument
than as a set of numbers.

**Attention Is All You Need** (Vaswani et al., 2017) — *skim,* on the annual re-read. Mostly
useful now as a reminder of how small the original model was.

## Books

**Designing Data-Intensive Applications** (Kleppmann) — *keep.* Chapters 3 and 5 this month;
notes in [[designing-data-intensive-applications]]. Not an AI book, which is why it is
useful: retrieval is a storage-and-indexing problem wearing a new hat.

**The Pragmatic Programmer** — *skim.* Re-read the chapter on tracer bullets, which is
roughly what the notes server was: thinnest possible path through the whole protocol,
end to end, before adding anything.

## Blog posts and talks

- A good post arguing that evaluation harnesses are the only durable artifact in an AI
  codebase. Agreed loudly; see [[evals-first]].
- A talk on context budgets that finally gave me vocabulary for what I had been doing by
  instinct. Fed into [[context-engineering]].
- Two posts about agent tool design that disagreed with each other. The disagreement was the
  useful part — [[tool-design-for-agents]].

## Verdict on the month

Too much reading, not enough building, right up until the last week. The build log in
[[building-a-notes-server]] taught me more per hour than anything above, because it forced
the reading to cash out into a running process.
