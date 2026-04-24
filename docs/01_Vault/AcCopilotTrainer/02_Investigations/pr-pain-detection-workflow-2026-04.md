---
title: PR pain detection → process-learning backlog (Workstream B)
date: 2026-04-20
status: implemented
related:
  - "[[post-merge-determinism-overhaul-2026-04]]"
  - "[[../03_Decisions/_index]]"
tags: [post-merge, process-mining, learning-loop, pr-pain]
---

# Context

Workstream A (PR #88) made the post-merge steward deterministic. The remaining
half of the original problem — *"the post-merge process should detect pain in
a PR and force learning, not just classify and forget"* — is Workstream B.

The user's concrete framing: imagine a single PR with **36 commits and
hundreds of reviews** in a new area (e.g. dial sandbox). Today nobody flags
it. Tomorrow we want a system that:

1. Quantifies the iteration cost ("pain") in a transparent, auditable way.
2. When pain is high, files an issue in `template-repo` describing the
   pattern, not the individual PR.
3. A future RMS / process-miner agent picks up the issue, runs
   `tools/process_miner/` scoped to the painful PR, and proposes concrete
   skill / rule / hook updates that propagate through Copier.
4. Cross-repo dedup: the same pain pattern across N repos should land on a
   *single* backlog issue, not N copies.

# Decisions

## D1 — Linear, transparent score (no ML)

```
pain = 1.0 * commits_after_first_review
     + 0.5 * fix_commits
     + 0.3 * human_review_comments
     + 0.1 * bot_review_comments      # low weight — Mistral was right that bot noise inflates
     + 2.0 * ci_red_runs              # heaviest weight: red CI = wasted time
     + 1.0 * days_open_after_first_ready_for_review

high   ≥ 25.0
medium ≥ 12.0
low    <  12.0
```

Calibration sanity:

- Healthy PR (2 commits after, 0 fix, 5 human, 20 bot, 0 red, 1 day) ≈ 6.5 → low ✓
- Medium-pain PR (8 / 2 / 15 / 40 / 1 / 3) ≈ 22.5 → medium ✓
- Reference 36-commit PR (36 / 5 / 50 / 150 / 5 / 7) ≈ 85.5 → high ✓

Tune from real data after 5–10 merges have been scored. Threshold constants
live in `tools/pr_pain/pain_score.py` so changes are auditable in PRs.

## D2 — Fingerprint by top-3 changed first-segment dirs

Cross-repo dedup uses `sha256(sorted(top_3_dirs))[:12]`. Same pattern across
repos → same fingerprint → single issue with multiple linked PRs. Avoids the
"50 issues, all about `.github/workflows/`" failure mode.

Trade-off accepted: granular bug clusters that touch the same top-level dir
collapse together. Acceptable for v1 — the linked PRs list disambiguates, and
the issue body suggests running `process_miner` for the actual pattern.

## D3 — Filing strategy: title-based dedup, body marker as backup

- Title format: `Process learning: pain pattern in '<top-dir>' [fp:<hex>]`.
- Search: `[fp:<hex>] in:title is:open label:process-learning`.
- Body contains `<!-- pr_pain_fingerprint: <hex> -->` for sanity / future
  GraphQL-based dedup if title search ever fails us.
- On dedup hit: append PR to "Linked PRs" section, post a comment with the
  new PR ref + new score. Issue stays open; closure is a human/RMS decision.

## D4 — Allowlist gate (`.github/pr-pain-config.yml`)

Filing only happens for repos in `enabled_repos`. Start with
`agorokh/template-repo` only. Add `agent-factory` / `workstation-ops` after
the first cycle of real data confirms scores are sane.

`dry_run_repos` gives a "score-but-don't-file" mode for safe rollout.

## D5 — Workflow lives in `template-repo`, dispatched by children

`pr-pain-detection.yml` runs in `template-repo` with three triggers:

- `pull_request: closed` for `template-repo`'s own merges (self-feedback)
- `workflow_dispatch` for manual scoring of any repo (debug / backfill)
- `repository_dispatch` (event type `pr-pain-eval`) for child-repo dispatchers

The child-repo dispatcher is **not shipped in this PR**. Sequence:

1. Merge this PR. Validate self-scoring on `template-repo` PRs for ~1 week.
2. Tune thresholds from real data.
3. Add a tiny `dispatch-pain-eval.yml` to the Copier template that fires on
   child PR merge → `template-repo` `repository_dispatch`. Ship via
   `template-sync.yml`.

This sequencing matches the user-approved plan: "land workstream B, validate
on a couple real merges, then propagate."

## D6 — Workflow MUST NOT block merges

The workflow runs *after* merge (`pull_request: closed`). Any failure here
logs `::error::` but cannot affect merge outcomes. This is non-negotiable —
Workstream A's whole point was to stop post-merge ops from blocking flow.

# Architecture summary

```
[child PR merges]
        │
        │ repository_dispatch (added later)
        ▼
[template-repo / pr-pain-detection.yml]
        │
        ├─ tools/pr_pain/pain_score.py (gh CLI → JSON)
        │
        ├─ check .github/pr-pain-config.yml (allowlist)
        │
        └─ if level != low → tools/pr_pain/file_issue.py
                │
                ├─ search by [fp:<hex>] → existing? append : create
                │
                └─ labels: process-learning, from:<repo>, pain:<level>
                          ▼
              [process-learning issue in template-repo]
                          │
                          ▼
              [future RMS agent / explicit user run]
                          │
                          └─ runs tools/process_miner/ scoped to linked PRs
                                  → proposes skill / rule / hook updates
                                  → opens template-repo PR
                                  → template-sync.yml propagates to children
```

# Open questions / follow-ups

- **PAT for cross-repo filing.** When child repos start dispatching, the
  workflow needs `issues:write` on `template-repo`. The workflow already
  reads `secrets.PAIN_REPORT_TOKEN` and falls back to `github.token` (which
  works for self-PRs only). Provision the PAT at the same time as the child
  dispatcher rolls out.
- **Threshold tuning.** Recompute `THRESHOLD_HIGH` / `THRESHOLD_MEDIUM` from
  the first 10 scored PRs. Aim for ~10–20 % of merges flagging.
- **Fingerprint quality.** Top-dir bucketing is coarse. If we see >5 issues
  collapsing onto `process-learning: pain in '.github/workflows/'`, refine
  the fingerprint (e.g. include 2nd-level dirs or skill names).
- **Cycle closure.** When an RMS agent ships a fix, it should comment on the
  process-learning issue and close it. Add this to `process_miner` as a
  follow-up.

# Why split A and B

Workstream A (PR #88) is *infrastructure* — it has to land cleanly and be
boring. Workstream B is *policy* — thresholds and fingerprints will need
tuning. Keeping them separate lets us iterate on B without re-touching the
deterministic core.

# Rollback

If the workflow misfires (false-positive issue floods, crashes on edge-case
PRs):

1. Set `enabled_repos: []` in `.github/pr-pain-config.yml` and merge — kills
   filing without removing the code.
2. To fully disable scoring: rename `pr-pain-detection.yml.disabled` (a
   one-line PR).

The investigation note + this PR's commit message should be enough for any
agent to root-cause a failure.
