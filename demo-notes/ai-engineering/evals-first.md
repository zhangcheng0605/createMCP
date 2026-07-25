---
title: Evals before features
tags: [ai-engineering, evaluation, process]
updated: 2026-07-09
---

# Evals before features

The most expensive habit in this field is shipping a prompt change because the three examples
you tried by hand looked better. I have done it. It feels like progress and it is a random
walk.

## The rule I hold myself to

Before changing behaviour, write down how you will know it improved. Not a benchmark — a
scoring harness, however crude. Twenty labelled cases in a CSV beats zero cases and a good
feeling.

## What a minimum viable eval looks like

- **A set of inputs** drawn from real usage, including the three failures that annoyed you
  most this week.
- **A grader.** Exact match where you can get away with it, a checklist where you cannot, a
  model-as-judge only when the first two are impossible — and then spot-check the judge.
- **A number and a date**, committed to the repo next to the code. Trend beats absolute.

## Failure modes I keep hitting

- **Grading on the training set.** If you tuned the prompt while staring at those cases, they
  are no longer evidence. Hold out a slice you never look at.
- **One aggregate number.** An average hides the regression that matters. Slice by category.
- **Judge drift.** A model-as-judge grader is a model, with its own version and its own
  quirks. Pin it, and re-validate when it changes.
- **Scoring the shape, not the substance.** It is easy to write a grader that rewards
  confident formatting. Ask what a lazy answer would score.

## Why this shows up in a protocol project

The same argument applies one level down. A live integration test that launches the server
and drives the real handshake is an eval: it defines "working" in a way that survives me
forgetting the details. Everything in [[debugging-with-mcp-inspector]] is manual QA, which
is fine for a demo and useless as a regression net.

## See also

- [[tool-design-for-agents]] — the interface is a variable you should be measuring.
- [[2026-07 reading log]] — a couple of good pieces on evaluation this month.
