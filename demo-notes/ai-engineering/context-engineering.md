---
title: Context engineering
tags: [ai-engineering, retrieval, context]
updated: 2026-07-15
---

# Context engineering

"Prompt engineering" undersells the job. Most of the work is deciding what information is in
the window at the moment the model answers, and what is deliberately left out.

## The budget framing

Treat the window as a budget with four competing line items:

1. **Instructions** — who the model is, what it must not do. Small, stable, cacheable.
2. **Tools** — every tool definition is tokens, spent on every single turn.
3. **Retrieved content** — the expensive, variable part.
4. **History** — grows without bound unless you do something about it.

Anything that is always present should be at the front and stable, so the prefix can be
cached. Anything variable goes late.

## Long windows did not delete retrieval

They changed the reason for it. Retrieval used to be about *fitting*; now it is about
*attention and cost*. A million tokens of vaguely related material buys you a slower, more
expensive, and often less accurate answer than four well-chosen pages. Precision beats
recall once the window stops being the binding constraint.

Corollary: measure retrieval on whether the final answer got better, not on whether the top-k
looked plausible to you.

## The tiered approach I default to

- **Tier 0:** literal keyword search over a small corpus. Boring, fast, debuggable, and
  frequently enough — this is what [[building-a-notes-server]] does, and for a few hundred
  notes I have not needed more.
- **Tier 1:** add embeddings when users phrase things differently from the documents. Hybrid
  with keyword search; do not replace it.
- **Tier 2:** rerank, and only then start caring about chunking strategies.

Skipping to Tier 2 first is the most common self-inflicted wound I see.

## Let the model do the retrieving

The nicer pattern, once tools exist, is to stop stuffing context up front and let the model
search. Give it a good search tool and a good read tool and it will do two or three targeted
lookups instead of one blind similarity query. That is exactly the loop the notes server is
built around — search first, then read the full note if more context is needed.

This is also the strongest argument for the primitives in [[MCP resources vs tools]]: the
model controls the tools, so the model controls its own context budget.

## See also

- [[paper-notes-retrieval-augmented-generation]] — where the pipeline shape came from.
- [[evals-first]] — you cannot tune any of this without a scorer.
- [[tool-design-for-agents]]
