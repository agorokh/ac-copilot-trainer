---
name: github-issue-creator
description: Create well-structured GitHub Issues with mined pitfall intelligence. Use when the user asks to file an issue, split work, or capture acceptance criteria before coding.
allowed-tools: Read, Grep, Glob, Bash, Agent
---

# GitHub Issue Creator (with shift-left pitfall injection)

## Before writing

1. Read `AGENTS.md`, `docs/00_Core/SESSION_LIFECYCLE.md`, `docs/10_Development/10_Agent_Protocol.md`
2. Read vault `00_System/invariants/_index.md`
3. **Load pitfall rules** (see "Pitfall loading" below)

## Pitfall loading (hub-spoke)

Pitfalls live in the **template-repo hub** and are fetched at issue-creation time.

### Resolution order

1. Read `.claude/pitfalls-hub.json` for hub coordinates (`hub_repo`, `hub_path`, `hub_branch`)
2. **If this IS the hub repo** (current repo matches `hub_repo`): read pitfalls locally from `hub_path/` (skip `_index.md`, read only `*.md` pitfall files)
3. **If this is a child repo**: fetch pitfalls from hub via:

   ```bash
   gh api "repos/{hub_repo}/contents/{hub_path}?ref={hub_branch}" \
     --jq '.[] | select(.type=="file" and (.name | endswith(".md")) and .name != "_index.md") | .name'
   ```

   Then for each filename returned:

   ```bash
   gh api "repos/{hub_repo}/contents/{hub_path}/{filename}?ref={hub_branch}" \
     -H "Accept: application/vnd.github.raw"
   ```

4. **Fallback**: if `pitfalls-hub.json` is missing or `gh api` fails, skip pitfalls gracefully and note in the issue body: `> **Note:** Pitfall rules could not be loaded from the hub repository. Review manually.`

### Matching pitfalls to issue scope

Parse each pitfall's YAML frontmatter for `scope_paths` (glob patterns) and `domains`.

- Identify the files the issue is likely to touch (from the user's description, or by grepping for related modules)
- Match file paths against each pitfall's `scope_paths` using glob matching
- Also match by `domains` when you can resolve a domain tag: read `REPO_DOMAIN` in `tools/process_miner/fleet.py` if that file exists in this repo, otherwise the repo vault `Project State.md`. If no tag is found, skip domain filtering.
- If no domain metadata is available, skip domain filtering and rely on `scope_paths` matches only.
- Select the **top 3-5 matching pitfalls** by relevance (prefer higher severity, more canonical PRs).

## Issue body template

```markdown
## What
[One paragraph: what needs to change and why]

## Acceptance criteria
- [ ] GIVEN ... WHEN ... THEN ...
- [ ] GIVEN ... WHEN ... THEN ...

## Known pitfalls in this area
<!-- Auto-populated from template-repo hub pitfalls. See .claude/pitfalls-hub.json -->
- **[Pitfall title]** -- [One paragraph summary of the rule and why it matters].
  Canonical damage: [repo] PR #NNN -- [one-sentence description of what broke].
- **[Pitfall title]** -- [...]
  Canonical damage: [repo] PR #NNN -- [...]

## Implementation notes
[Optional: suggested approach, relevant files, architectural constraints]

## Out of scope
[What this issue explicitly does NOT cover]
```

### Key constraints for the "Known pitfalls" section

1. **3-5 bullets maximum.** Cheaper implementing models (Cursor Auto) skim long issues. Short, specific bullets survive the attention window.
2. **Always include PR citations.** Concrete examples ("PR #751 broke the kill switch") are more effective than abstract rules ("ensure proper error handling").
3. **File-path scoping prevents noise.** A pitfall about `agent/streaming/**` does NOT appear in an issue touching `analytics_ui/**`.
4. **Each bullet is one paragraph, not a novel.** The preventive rule from the pitfall file, condensed.

## Labels and metadata

Suggest labels (type, priority, area) consistent with team practice in `AGENTS.md`.

## Branch hint

Include a suggested branch name matching `AGENTS.md` conventions (e.g., `feat/issue-NNN-short-slug`).

## Group by files touched

Per AGENT_CORE_PRINCIPLES.md: never create separate issues that modify overlapping source files. Consolidate into one issue with labeled Parts.

---

**Cursor mirror:** `.cursor/skills/github-issue-creator/SKILL.md` is a thin pointer to this file; update both when changing workflow.
