---
title: Paper notes — Retrieval-Augmented Generation
tags: [reading-log, paper-notes, retrieval]
updated: 2026-07-08
---

# Paper notes — Retrieval-Augmented Generation

*Lewis et al., 2020. Re-read July 2026.*

## The claim

Instead of hoping a model memorised a fact during training, give it a retriever over a
non-parametric store and let it condition generation on what comes back. Parametric memory
for language and reasoning; non-parametric memory for facts.

## Why it aged well

- **Updating the index beats retraining.** Change the documents, change the answers. This is
  still the single strongest practical argument for the whole approach.
- **Attribution comes for free-ish.** If the answer came from a retrieved passage, you can
  point at the passage. Every serious deployment I have seen ends up needing this.
- **Separation of concerns.** The retriever and the generator can be improved
  independently, which means two smaller problems instead of one enormous one.

## Why the specifics aged less well

- The dense-retriever-plus-seq2seq architecture has been thoroughly overtaken. Read it for
  the shape of the argument, not the implementation.
- Chunking, which consumes an unreasonable share of practitioner attention today, is barely
  a footnote here.
- The paper predates tool use entirely. Today a capable model can *decide* to retrieve, more
  than once, refining as it goes — which is a qualitatively different loop than
  retrieve-once-then-generate. That shift is the thread I pull on in
  [[context-engineering]].

## Line I underlined

> The retrieved documents act as a latent variable.

Useful reframing: retrieval quality is not a separate scoreboard, it is part of the model's
inference. Which is exactly why it has to be measured on final answer quality
([[evals-first]]) rather than on top-k relevance judged by eye.

## Connection to what I am building

My notes server is a deliberately Tier-0 version of this: keyword search over a folder,
returning URIs the model can then read. No embeddings, no store, no pipeline. The interesting
part is not the retrieval quality — it is that the model drives the loop through a tool
instead of receiving a pre-stuffed context. See [[building-a-notes-server]] and
[[MCP resources vs tools]].

## See also

- [[2026-07 reading log]]
- [[designing-data-intensive-applications]] — indexing, from the database side.
