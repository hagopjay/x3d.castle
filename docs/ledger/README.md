# A ledger for the numbers the docs state

Every number in the README and the docs names the file it came from. This folder checks that, by code, for the ones that can be checked offline.
`claims.jsonl` has one line per number: the doc that states it and the words it states it in (`where`, `where_quote`), the value, the file it comes from
(`source`) and how the file gives it (`op`): a quote that holds the value, a sum or count recomputed from a JSON result, or a line count.

```bash
python3 -I -B docs/ledger/check_ledger.py                 # every entry, exit 1 if one is `check`
python3 -I -B -m unittest discover -s docs/ledger -v      # 6 tests of the checker
```

Verdicts are `verified` (the words are in the doc, the value is written inside them, and the source gives the same value) and `check` (the doc says something the file does not
give). It is the FIND / COMPARE / LOCATE check of source tracing, applied to documentation: it says the doc and the file agree, not that the file is right.
It lives in `docs/` and not in `tools/` on purpose: the Docker workflow's path filter includes `tools/**` and would start its 45-minute job for a pure-Python change.

## What it found the first time

`README.md` said the exporter is "about 1,700 lines of Pascal" and `docs/exporter.md` said "about 2,500"; `castle-convert/x3dcastleexport.pas` has 2,412 lines at `0a1073f`.
Both now say about 2,400, and entries L-8 and L-9 keep them honest within 1%. The other seven entries (the stock writer's 24 of 70 failing and 14,379 errors, the exporter's
70 of 70 clean, and the census rows for lights, cameras, vertex colours and textures) all verified against `results/`, Python 3.13.18, 2026-11-16.

## What it does not cover

- Source citations into the Castle engine (`file:line` ranges in `docs/quality-levers.md`) and spec clauses in `docs/exporter.md` and `docs/castle-gaps.md`: they need a pinned
  Castle commit (the Docker image pins the release bundle by sha256, not a source tree) or a fetch of the spec page. A scout pass on 2026-11-16 found all 46 cited ranges
  non-empty on Castle's `master` and the quoted 17.2.2.3 and 17.2.2.6 formulas in the spec page, but `master` is not the snapshot the docs were written against, so none of that is in this ledger.
- A number that is derived (a ratio, a median over a run) is covered only if a `sum`, `count` or `quote` entry can reach it.

The method comes from Umair Ali Khan's article on traceability in structured data extraction and the GAIK toolkit (MIT). This checker is original code and uses none of theirs.
