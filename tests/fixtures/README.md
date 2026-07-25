# Test fixtures

`tests/fixtures/notes/` is the notes directory used by the test suite (`NOTES_DIR` points
here for the integration test). It is **purpose-built for assertions** — small, deterministic,
and deliberately unlike `demo-notes/`. Do not "improve" the prose: the word counts below are
load-bearing.

## Layout

```
tests/fixtures/notes/
├── Spaced Note.md          # top-level filename WITH A SPACE
├── alpha.md
├── beta.md
├── gamma.md
├── .obsidian/
│   └── hidden.md           # MUST BE SKIPPED (hidden directory)
└── nested/
    ├── deep.md             # proves recursive scanning
    └── ignored.txt         # MUST BE IGNORED (not .md)
```

**Exactly 5 markdown files are in scope**, and their relative paths sort like this
(plain ASCII `sorted()` on the relpath — note that uppercase `S` sorts *before* lowercase):

1. `Spaced Note.md`
2. `alpha.md`
3. `beta.md`
4. `gamma.md`
5. `nested/deep.md`

Expected URIs (three slashes, `urllib.parse.quote` applied to the relpath):

| relpath | URI |
|---|---|
| `Spaced Note.md` | `notes:///Spaced%20Note.md` |
| `alpha.md` | `notes:///alpha.md` |
| `beta.md` | `notes:///beta.md` |
| `gamma.md` | `notes:///gamma.md` |
| `nested/deep.md` | `notes:///nested/deep.md` |

Note that `quote()` does **not** escape `/` by default, so the nested URI keeps its slash.

## Term counts (the important part)

Counts are per file, for the in-scope markdown files only. Every term below appears **only as
the exact bare word** — no plurals, no substrings inside longer words — so substring counting
(`str.count`) and word-boundary counting (`\bterm\b`) give identical results. Term matching is
case-insensitive; all occurrences are already lowercase.

| term | `alpha.md` | `beta.md` | `gamma.md` | `Spaced Note.md` | `nested/deep.md` |
|---|---|---|---|---|---|
| `widget` | **4** | 2 | 1 | 0 | 0 |
| `tiebreak` | 0 | **1** | **1** | 0 | 0 |
| `gizmo` | **1** | 0 | 0 | 0 | 0 |
| `quantum` | 0 | 0 | 0 | **2** | **1** |
| `ferret` | 0 | 0 | 0 | **1** | **1** |
| `zzznotfound` | 0 | 0 | 0 | 0 | 0 |

Each `widget` occurrence in `alpha.md` is on its own line (4 distinct matching lines), and each
`widget` occurrence in `beta.md` is on its own line (2 distinct matching lines). This supports
the "at most 3 matching lines per file" cap: `alpha.md` has 4 candidate lines and must show 3.

## Which property each fixture exists to support

| fixture | test property |
|---|---|
| `alpha.md` / `beta.md` / `gamma.md` | **Rank ordering.** Query `widget` → exactly these 3 files, in the order `alpha.md`, `beta.md`, `gamma.md` (4 > 2 > 1 occurrences). Also drives `max_results` clamping tests: with `max_results=1` only `alpha.md` comes back. |
| `nested/deep.md` + `Spaced Note.md` | **Phrase bonus.** Query `quantum ferret` → `nested/deep.md` must rank **first** even though `Spaced Note.md` contains more individual word occurrences. Word-only scores are 2 (`deep.md`) vs 3 (`Spaced Note.md`); the `+2` bonus for the one intact `quantum ferret` occurrence flips it to 4 vs 3. Without the phrase bonus this test fails, which is the point. |
| `beta.md` + `gamma.md` | **Deterministic tie-break.** Query `tiebreak` → both score identically (1 occurrence each); output order must be `beta.md` then `gamma.md`, i.e. relative path ascending. |
| `alpha.md` (`gizmo`) | **Single-hit search.** Query `gizmo` → exactly one result. |
| (`zzznotfound`) | **No-match path.** This string appears in no in-scope file; query it to test the "no matches, try broader terms" message. |
| `Spaced Note.md` | **Percent-encoding round-trip.** Top-level filename with a space — the exact case that crashes under a two-slash URI scheme (see SPEC §5). Must list as `notes:///Spaced%20Note.md`, and `read_note` must accept both that URI and the raw relpath `Spaced Note.md`. |
| `nested/deep.md` | **Recursive scanning.** Confirms subdirectories are walked and that a nested relpath survives the URI round-trip. |
| `nested/ignored.txt` | **Non-`.md` files are ignored.** It is stuffed with `widget` (9×), `quantum ferret` (3×), `tiebreak` (3×), `gizmo` (3×) — so if the scanner ever picks up non-markdown files, it will outrank everything and the ranking tests fail loudly instead of silently. |
| `.obsidian/hidden.md` | **Hidden directories are skipped.** Same trick: `widget` (7×), `quantum ferret` (2×), `tiebreak` (2×), `gizmo` (2×). If hidden-dir skipping regresses, this file wins every query and several tests break. It must never appear in `resources/list`, `list_notes`, or search results. |

## Caution on asserting exact scores

Prefer asserting **ordering and membership** over exact numeric scores — ranking is the
contract, the absolute number is an implementation detail.

For the record, the scoring rule is: occurrences of each query word, plus `+2` per intact
occurrence of the whole query **when the query has two or more words**. A single-word query
gets no phrase bonus, because the "phrase" would be the word the count already covered — so
`widget` in `alpha.md` scores **4**, not 12. (An earlier draft of SPEC §6.1 read as though the
bonus applied unconditionally; applying it to single-word queries would multiply every score
by 3× and change no ordering at all. The spec now says multi-word only, matching the code.)

## Also available

`demo-notes/` at the repo root is the curated folder for the screen recording — larger, prose
heavy, full of `[[wikilinks]]`. It is **not** a test fixture; do not point tests at it, since
its content is expected to be edited for demo purposes.
