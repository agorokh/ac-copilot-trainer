---
name: release-notes
description: Maintainer workflow for template release blurbs (e.g. template-YYYY.MM). Run only when explicitly asked — gathers git history and groups changes for a GitHub Release or PR description.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash
---

# Release notes (template maintainers)

Human-gated: the model should not run this autonomously. **User invokes** when drafting a template release.

Cross-link: **[Versioning](docs/00_Core/MAINTAINING_THE_TEMPLATE.md#versioning)** in `docs/00_Core/MAINTAINING_THE_TEMPLATE.md` (optional `template-YYYY.MM` tags after meaningful governance updates).

## Steps

1. **Choose the range**
   - Default: commits on `main` since the last `template-*` tag, or
   - User supplies `BASE..HEAD` SHAs or tag names.

2. **Collect commits (read-only git)**

   ```bash
   git fetch origin
   git log --oneline BASE..HEAD
   ```

   Replace `BASE..HEAD` with the chosen range (e.g. `template-2026.02..main`).

3. **Group into themes** (adjust labels to fit the batch):
   - **Governance** — hooks, agents, skills, AGENTS/CLAUDE, vault protocol
   - **Dependencies** — Dependabot, `pyproject.toml`, lockfiles if any
   - **CI / automation** — workflows, scripts, pre-commit
   - **Docs** — README, WARP, TOOLCHAIN, setup guides

4. **Draft markdown** suitable for a **GitHub Release** body or a governance PR description:
   - Short summary line, then bullet sections per theme
   - Link to notable PRs/Issues when helpful

5. **Secrets and redaction**
   - Do **not** paste tokens, PATs, or private hostnames from commit messages or logs.
   - Redact or paraphrase if history contains sensitive strings.

6. **Tags and publishes**
   - Creating tags, GitHub Releases, or any **write** to remote is **human** — the skill stops at drafted markdown unless the user explicitly runs those commands themselves.
