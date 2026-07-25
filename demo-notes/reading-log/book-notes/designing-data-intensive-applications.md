---
title: Book notes — Designing Data-Intensive Applications
tags: [reading-log, book-notes, systems]
updated: 2026-07-19
---

# Book notes — Designing Data-Intensive Applications

*Kleppmann. Chapters 3 and 5, July 2026.*

Not an AI book. I keep coming back to it anyway, because most of what gets called
"AI infrastructure" is storage and indexing with a fashionable interface.

## Chapter 3 — storage and retrieval

The central move is to stop treating an index as magic and see it as **a derived structure
you pay for on write to save on read**. Every index is a bet about the query pattern.

Things worth carrying over:

- **Log-structured versus page-oriented** is a throughput-versus-latency tradeoff, not a
  correctness one. Vector stores are re-litigating the same tradeoff under new names.
- **A full scan is not shameful at small n.** My folder of a few hundred notes is scanned
  linearly on every query and it returns instantly. Building an index first would have been
  pure ceremony — the tiering argument in [[context-engineering]].
- **Column orientation wins when you touch few fields of many rows.** Analogous, loosely, to
  why returning matching *lines* beats returning whole documents.

## Chapter 5 — replication

Read mostly for the vocabulary: leader/follower, replication lag, read-your-writes. Not
directly relevant to a single-process local server that owns one folder, and it was clarifying
to notice *why* it is not relevant — one process, one reader, no writes, no distributed state.
Half of engineering is knowing which chapter you are not in.

## The transferable lesson

Ask what the query pattern actually is before choosing the data structure. Most retrieval
systems I have seen were designed for an imagined query pattern and then never measured
against the real one.

## See also

- [[paper-notes-retrieval-augmented-generation]]
- [[2026-07 reading log]]
- [[building-a-notes-server]] — the smallest possible storage layer: the filesystem.
