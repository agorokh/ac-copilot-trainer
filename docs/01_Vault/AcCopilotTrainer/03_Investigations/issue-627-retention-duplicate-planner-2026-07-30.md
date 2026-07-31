---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-30
updated: 2026-07-30
issue: https://github.com/agorokh/ac-copilot-trainer/issues/627
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-627-journal-scan-stall-2026-07-30.md
  - AcCopilotTrainer/03_Investigations/issue-627-postlap-freeze-same-loop-2026-07-30.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
---

# Lap retention: I built a duplicate planner, and the real bug was in the original

Follow-up to [[issue-627-journal-scan-stall-2026-07-30]]. Closing #627 left two items: make the
imported-reference scan cheap for users who *enable* it, and bound the lap journal. The second
item is where the lesson is.

## What I got wrong

I wrote `tools/journal_prune.py` on the premise that **the journal grows without limit**. It does
not. `lap_archive.M.rotate` runs after every completed lap and evicts oldest-first under a size
cap (default 500 MB, floor 50 MB). The rig's measured **403 files / 486 MB is that cap working**,
not runaway growth.

Worse, `tools/coaching_lake/retention.py` (issue #402) **already was** the tool I was writing, and
strictly stronger: it protects `lap.is_pb`, driver-profile PB uuids, `source:"imported"` (plus
`import_format` / `generator`), `.pin`/`.keep` markers, and unreadable archives, and it orders by
the record's `exported_at` with mtime only as a fallback. My version had none of that.

Both facts surfaced from **review**, not from my own search: a code-reviewer agent found `rotate`,
the Codex bot found `retention.py` by way of a cluster of P1s about missing protections. Neither
would have been caught by testing my tool harder — the tool was the wrong artifact.

## The bug that was actually there

Every protection in the canonical planner is **record-local**. It reads each archive and decides
from that archive's own contents. It therefore cannot see that some *other* file still points at
it. On the rig, `journal/reports/*.json` cites **187** archives the planner classified `eligible`:

| | delete candidates | protected | scanned |
|---|---|---|---|
| before | 303 | 97 | 403 |
| after | 178 | 225 | 403 |

**125 archives the operator's own session reports still cite were one `--apply` from deletion**,
in code shipped since #402.

`_cited_archive_names` closes it. Design points worth keeping:

- Scans `*.json` **and `*.jsonl`** — `journal/setup_experiments/experiments.jsonl` records an
  `archive_path` per row and a `*.json` glob misses it entirely.
- Token requires the `.json` suffix, so `lap_history` / `lap_ms` cannot masquerade as citations.
- Excludes `journal/laps`: archives must not keep each other alive.
- **Fails closed.** An unreadable state file protects everything. An empty citation set is what
  makes an archive *eligible*, so "I could not read it" must never be spelled the same way as "it
  cites nothing". This is the asymmetry that made the first version dangerous.

## Two more data-loss paths, same theme

1. **`lap_archive.rotate` had no source check.** Imported references survived only because the
   sort is alphabetical and `lap_<YYYYMMDD…>` precedes `lap_imported_…` (digits before `i`). An
   accident, and it stops holding once every in-game archive has been evicted and the directory is
   still over cap. Now skipped explicitly; if imports alone exceed the cap, the cap is exceeded.
2. **The Lua prefilter's tolerant path took the first `source` match.** For a pretty-printed
   archive with a nested `source` ahead of a top-level `"source": "imported"`, it returned
   `false` — *proven not imported* — and silently dropped the user's lap. Now scans every match,
   mirroring the compact fast path's whole-buffer OR.

## Transferable lessons

- **Search for the existing subsystem before building the tool.** "Does the repo already do this?"
  was a five-minute grep I did not run. Reviewers spent their budget telling me things
  `tools/coaching_lake/retention.py` already knew.
- **State the premise as a claim and check it.** "The journal grows without limit" was assumed
  from a directory listing. One `grep rotate` refuted it.
- **A protection that can fail to evaluate must fail closed.** Three separate defects on this
  branch were the same shape: an inability to verify a protection being encoded identically to the
  protection not applying.
- **Deleting your own work is a valid resolution to a review.** Ten P1/P2 findings collapsed to
  "this file should not exist"; only one — the citation scan — was worth keeping, and it belonged
  in the canonical planner.
