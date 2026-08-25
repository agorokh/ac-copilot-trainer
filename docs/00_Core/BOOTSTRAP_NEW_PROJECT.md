# Bootstrap a new project from this template

Complete these steps once per new repository.

## 0. Copier (recommended)

This repository is a **[Copier](https://copier.readthedocs.io/)** template (`copier.yml` at the root). Prefer generating a new project from a **tag** (e.g. `template-2026.03`) or `main`:

```bash
pip install copier   # or: pip install -e ".[bootstrap]" from a clone
copier copy gh:YOUR_ORG/template-repo path/to/new-repo
cd path/to/new-repo
# Answer prompts: project_name, project_key, package_name, github_org
make ci-fast
```

Copier runs `scripts/copier_post_copy.py` after copy to rename `docs/01_Vault/AcCopilotTrainer` → `docs/01_Vault/<project_key>`, `src/project_template` → `src/<package_name>`, patch `pyproject.toml`, and replace canonical path strings across text files. Files matching `_skip_if_exists` in `copier.yml` are not overwritten on **update**.

**Updates in an existing child repo** (after the first `copier copy`):

```bash
copier update --trust
```

Use the reference workflow `.github/workflows/template-sync.yml` (optional) for scheduled or manual sync PRs; see [MAINTAINING_THE_TEMPLATE.md](MAINTAINING_THE_TEMPLATE.md).

**Canonical template identity:** To work in **this** template repository unchanged, use default answers `project_key=AcCopilotTrainer`, `package_name=project_template`, `project_name=project-template`.

## 1. Identity (manual bootstrap)

If you did not use Copier, complete these manually:

- [ ] Choose a **project key** (short, filesystem-safe, e.g. `AcmePlatform`). You will rename the vault folder to match.
- [ ] Update `pyproject.toml`: `name`, `description`, and `[tool.setuptools.packages.find]` / package layout if you change `src/project_template`.
- [ ] Replace the Python package `src/project_template/` with your package name (or keep and rename in one commit).

## 2. Vault (Obsidian knowledge graph)

- [ ] Rename `docs/01_Vault/AcCopilotTrainer` → `docs/01_Vault/<YourProjectKey>`.
- [ ] Keep **`docs/01_Vault/00_Graph_Schema.md`** at vault **parent** level (it is intentionally outside the renamed folder).
- [ ] Global find-replace `AcCopilotTrainer` → `<YourProjectKey>` in:
  - `CLAUDE.md`
  - `docs/01_Vault/00_Graph_Schema.md` (especially `relates_to` entries such as `AcCopilotTrainer/00_System/...`)
  - (the `vault-memory` skill is machine-level at `~/.agents/skills/` and generic — do **not** edit it during bootstrap; it resolves the project key from the repo's vault layout)
  - `.claude/rules/memory.md`, `.claude/rules/invariants.md`
  - `.claude/settings.json` (Stop / hook reminder paths)
  - `.cursor/rules/invariants.mdc`, `.cursor/BUGBOT.md`
  - `AGENTS.md`, `.cursorrules` (if they reference the old path)
  - **GitHub custom agents:** `.github/agents/issue-refiner.agent.md` — replace `docs/01_Vault/AcCopilotTrainer/...` with `docs/01_Vault/<YourProjectKey>/...` (see HTML comment in that file).
- [ ] **Restructure nodes** for your domain: add invariant nodes, glossary terms, and ADRs as small linked files; update `_index.md` files accordingly (see `00_Graph_Schema.md`).
- [ ] Update **`relates_to` / `part_of`** in vault YAML: replace the `AcCopilotTrainer/` prefix with `<YourProjectKey>/` in every anchored path (paths are relative to `docs/01_Vault/`; no `..` segments — see `00_Graph_Schema.md`).
- [ ] Open the vault in Obsidian (optional: tune `.obsidian/` plugins — keep REST API off unless you intend to use it).

## 3. Agent docs

- [ ] Edit `AGENTS.md` **Core Principles** and **Repository Layout** for your domain.
- [ ] Edit `AGENT_CORE_PRINCIPLES.md` **Architecture Overview** and **What NOT to Do** for your stack.
- [ ] Edit `docs/10_Development/10_Agent_Protocol.md` file-placement table and forbidden actions.
- [ ] Edit `docs/10_Development/11_Repository_Structure.md` and `scripts/check_agent_forbidden.py` `ALLOWED_TOPLEVEL_DIRS` (and root file allowlist if you add new top-level files).
- [ ] Optional: add project-specific sections to `AGENTS.md` § Local development.
- [ ] **Do NOT rename** `hub_path` in `.claude/pitfalls-hub.json` — child repos intentionally read pitfalls from the template-repo hub (hub-spoke architecture), not locally.

## 4. Hooks, invariants, and lifecycle

- [ ] Replace template **invariant** stubs under `docs/01_Vault/<YourProjectKey>/00_System/invariants/` with your real rules (or add nodes); keep `invariants/_index.md` current.
- [ ] Adjust `.claude/settings.json` PreToolUse prompts if your code lives outside `src/` or you need different string guards (gateways, DDL location, etc.).
- [ ] If raw evidence or large data must never be agent-written, add a shell hook (see disclosures-style `block-data-edits.sh`) and wire it in `settings.json`.
- [ ] Read **`docs/00_Core/SESSION_LIFECYCLE.md`** and align team practice (LOAD → OPERATE → SAVE).

## 5. GitHub

- [ ] Set repository **Settings → Template repository** if this copy should be the next template.
- [ ] Update `.github/pull_request_template.md` and issue templates for your team.
- [ ] Replace `.github/agents/*.agent.md` with a real custom agent or delete if unused (avoid stale third-party names in prompts).

- [ ] **Settle CI compute BEFORE relying on CI — the copied lanes are all self-hosted, act by visibility.** An unserved lane **queues forever with no red build** (workstation-ops#2896, observed bootstrapping tuning-atelier). **Private child** → register a runner slot in **workstation-ops**: add `'<github_org>/<repo>': {instances: 1}` to `ops/github-runner/fleet.yaml` — in the host map whose runner labels match the copied lanes (default: the m1max map), add the matching `github-runner-<repo>` row to `ops/service.yaml` (`test_service_catalog_tracks_every_declared_slot` enforces the lockstep), then run reconcile `--apply` on that runner host. **Public child** → do **NOT** attach self-hosted runners (fleet policy `adr-2026-06-27-local-ci-compute-architecture` keeps public repos GitHub-hosted; no self-hosted runners on public fork-PR surfaces) — and note that going public needs a **full CI migration beyond `runs-on`**: hosted images, a review of the same-repo fork guards (drop only those gating ordinary CI — keep token-dependent safety skips), replacement of private `governance-hub` action callers, and the billed-runner rejection gates. File a dedicated CI-migration issue before flipping visibility, or keep the repo private. Defense-in-depth: the hourly registration sweep (workstation-ops#2908) flags a starving private lane within ~90 minutes of its first stale dispatch.

## 6. MCP and local LLMs

- [ ] Confirm `.mcp.json` carries only repo-local servers launched via their wrappers (e.g. `repo-knowledge` via `bash scripts/mcp/repo-knowledge.sh`); GitHub work goes through the `gh` CLI. The retired github/context7 MCP servers must not be added (governance-hub#274; see [TOOLCHAIN.md](TOOLCHAIN.md), skill **`new-project-setup`**). <!-- mcp-retirement-ok -->
- [ ] Add database or browser servers only when the project needs them.
- [ ] Document API keys and local inference (Ollama, OpenRouter, HF caches) in `AGENTS.md` § Local development and annotated `.env.example` — never commit secrets. (`CLAUDE.md` should link there instead of duplicating.)

<a id="workstation-service-catalog"></a>

## 7. Workstation service catalog

> **Stable cross-reference anchor:** link to `#workstation-service-catalog` (the explicit ID above) rather than the auto-generated `#7-workstation-service-catalog`, so future renumbering does not break inbound links.

Once bootstrapped, this repo should declare workstation services in `ops/service.yaml`, consumed by [workstation-ops](https://github.com/agorokh/workstation-ops) for cross-repo service inventory, port-collision detection, and drift auditing. The template ships only `ops/service.yaml.example`; the live `ops/service.yaml` is created by step 1 of the checklist below.

- [ ] Copy `ops/service.yaml.example` → `ops/service.yaml`.
- [ ] **Manual bootstrap only:** replace the canonical placeholder `repo_id: project-template` with your project's actual repo name (must match the `repo_id` registered in `workstation-ops/ops/sources.yaml`). Copier-driven projects: `scripts/copier_post_copy.py` rewrites this automatically.
- [ ] Populate the `services:` list with any long-lived workstation services this repo exposes (launchd LaunchAgents, Docker containers, brew services, process-compose bundles). If this repo exposes none, keep `services: []` — the **explicit empty declaration** is intentional and tells workstation-ops this repo is catalog-aware with nothing to report. To add services, **delete the `[]`** and replace it with a YAML block list under `services:` (the commented examples in `ops/service.yaml.example` show the shape).
- [ ] Register the repo in [`workstation-ops/ops/sources.yaml`](https://github.com/agorokh/workstation-ops/blob/main/ops/sources.yaml). The `path:` field below assumes the conventional layout where `workstation-ops` and your project repo are sibling directories under a common parent (e.g. `~/Projects/workstation-ops` and `~/Projects/<your-repo>`); adjust the relative path if your checkout differs:

  ```yaml
  - repo_id: <your-repo>
    path: ../../<your-repo>/ops/service.yaml
    required: false
  ```

- [ ] Validate from the workstation-ops repository (e.g. `cd ../workstation-ops`): `make services-status` should include your services (or confirm your repo as catalog-aware with `services: []`).

**Out of scope** for `ops/service.yaml`: Claude Desktop / Claude Code MCP servers (stdio children, not workstation-supervised), AWS / cloud services (different host; catalog is Mac Mini-scoped), one-off scripts, CI-only services.

See [`ops/service.yaml.example`](../../ops/service.yaml.example) for the full schema reference and live-example links to agent-factory and Alpaca_trading.

## 8. Tier-3 semantic memory (optional)

If your repo will use Tier-3 semantic memory (an entity-relation / bi-temporal graph that complements `AGENTS.md` and the Obsidian vault), declare a workspace for it.

> **Declaring ≠ registering ≠ provisioning.** Naming a workspace in `AGENTS.md` or vault state is aspirational — it does *not* register or provision anything, and an agent must not treat a named-but-unregistered workspace as live. The three states (declared → registered → provisioned & visible), their deterministic gate behavior, and the correct agent action in each are defined in [MEMORY_CONTRACT.md § Workspace lifecycle](MEMORY_CONTRACT.md). **Until the substrate server is live, prefer leaving the workspace merely *declared*** (no manifest row): the memory gate then runs warn-only (bootstrap mode) and edits proceed against vault Tier-2 grounding. Add the manifest row below only when you intend to provision the server soon — a *registered* but unreachable workspace **hard-blocks** code-path edits by design ([issue #115](https://github.com/agorokh/template-repo/issues/115)), and adding a placeholder row to "satisfy the ladder" makes the gate stricter, not looser ([issue #169](https://github.com/agorokh/template-repo/issues/169)). **Exception:** if manifest-driven automation needs the row *before* provisioning — e.g. the observability exporter that watches `ops/memory_manifest.yml` so the workspace appears on the fleet dashboard ([ANTI_PATTERNS.md §3](ANTI_PATTERNS.md)) — register the placeholder row (`health_probe: false`, closed-loopback endpoint, like the `template_repo` row) **and accept the hard block** until provisioning lands; bypass per session with `CLAUDE_MEMORY_GATE=0` (audited in the vault SAVE). The "prefer merely declared" default is for the common case where you only need to keep editing freely pre-provisioning.

- [ ] Read [MEMORY_SUBSTRATE.md](MEMORY_SUBSTRATE.md) — substrate choice (`lightrag` canonical online; `graphiti` offline-only per the [Graphiti sunset ADR](https://github.com/agorokh/agent-factory/blob/main/docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-17-graphiti-sunset.md)).
- [ ] Read [VAULT_TAXONOMY.md](VAULT_TAXONOMY.md) — classify your vault as `repo-product` / `repo-embedded` / `human-curated`.
- [ ] Add a workspace row to [`ops/memory_manifest.yml`](../../ops/memory_manifest.yml) under the host that will own its ingest. Required fields: `name`, `backend`, `origin`, `endpoint`, `vault_root`, `audit_log`, `launchd_label`, `stale_after_hours`, and at least one `canary_queries[]` entry (each with `prompt` and `mode`). For `lightrag` workspaces (canonical), `launchd_label` typically follows `ai.lightrag.ingest-audit.<workspace_name>` (`null` if ingest is operator-managed externally). For offline-only `graphiti` workspaces, `launchd_label: null` (the shared offline MCP has no per-workspace plist).
- [ ] Pin `MEMORY_MANIFEST_REF` in Doppler to an immutable tag (e.g. `memory-manifest-v2`), never to `main`.
- [ ] For `lightrag` workspaces (canonical online), install the standard audit-ingest plist (`ai.lightrag.ingest-audit.<workspace_name>`) unless ingest is external — then set `launchd_label: null` and document why in workspace `notes`. For offline-only `graphiti` workspaces, no per-workspace launchd unit is needed (single shared MCP server, OFF the agent read path).

If your repo does NOT use Tier-3, skip this section. `AGENTS.md` + vault (Tier 1+2) work standalone.

## 9. Verify

```bash
make hooks-install
make ci-fast
```

**Manual bootstrap validation (not CI):** after renames and `pyproject` edits, run:

```bash
python3 scripts/check_bootstrap_complete.py
```

It warns if the vault folder, package directory, or `pyproject.toml` name still match template defaults. Intended for **local** use only. The script is **advisory**: it **always exits with code 0**; messages go to **stderr** when checks fail so you can use it in scripts without breaking pipelines.

## Post-bootstrap reading (agents and humans)

- [ ] [00_Graph_Schema.md](../01_Vault/00_Graph_Schema.md) — vault knowledge graph node schema and linking.
- [ ] [SESSION_LIFECYCLE.md](SESSION_LIFECYCLE.md) — mandatory session LOAD → OPERATE → SAVE protocol.
- [ ] [TOOLCHAIN.md](TOOLCHAIN.md) — Cursor, Claude Code, Desktop, MCP.

## Verification complete

Use this checklist before you call the repo “bootstrapped”:

- [ ] `docs/01_Vault/AcCopilotTrainer` renamed to your project key; `00_Graph_Schema.md` still at `docs/01_Vault/00_Graph_Schema.md`.
- [ ] `src/project_template/` renamed; imports and `pyproject.toml` package discovery updated.
- [ ] `[project].name` in `pyproject.toml` is not `project-template`.
- [ ] `python3 scripts/check_bootstrap_complete.py` prints no warnings.
- [ ] `.github/agents/issue-refiner.agent.md` (and any copied agent prompts) point at `docs/01_Vault/<YourProjectKey>/...`, not `AcCopilotTrainer`.
- [ ] `make ci-fast` passes; test PR confirms policy + CI workflows.
- [ ] CI compute settled per visibility: private → fleet row registered **and reconciled** (self-hosted lanes actually pick up the test PR's jobs); public → the dedicated CI-migration issue is **closed** (hosted images, fork guards reviewed, private-action callers replaced, billed-runner gates addressed) — or the repo stayed private. No self-hosted slot for public repos.
- [ ] Invariants and glossary indexes reflect your domain; new knowledge uses small linked nodes per `00_Graph_Schema.md`.
- [ ] `ops/service.yaml` exists with the correct `repo_id` and either a populated `services:` block or an explicit `services: []` (catalog-aware-no-services), and the repo is registered in `workstation-ops/ops/sources.yaml`.

## See also

- [TOOLCHAIN.md](TOOLCHAIN.md) — Cursor, Claude Code, Desktop, MCP.
- [OPTIONAL_CAPABILITIES.md](OPTIONAL_CAPABILITIES.md) — DB, AWS, HF, Ollama, browser tooling.
- [GITHUB_SETUP.md](GITHUB_SETUP.md) — branch protection, Dependabot, Copilot agents.
