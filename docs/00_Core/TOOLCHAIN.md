# Toolchain: Cursor, Claude Code, Claude Desktop

This template assumes **multiple surfaces** for the same repo. Policies in `AGENTS.md`, the vault, and GitHub stay **one source of truth**; each tool reads what it can.

## Required: Obsidian vault (Tier-2 memory)

- **Path:** `docs/01_Vault/AcCopilotTrainer/` (rename on bootstrap).
- **Why:** Structured ADRs, invariants, handoffs, and investigations do not belong scattered in chat logs.
- Open the folder as an Obsidian vault so humans can browse; agents follow `.claude/skills/vault-memory/SKILL.md`.

## Cursor

- **Rules:** `.cursorrules` + `.cursor/rules/*.mdc`.
- **Skills:** `.cursor/skills/` mirrors `.claude/skills/` for discoverability — **keep both copies in sync** when you edit a skill.
- **MCP:** **`.cursor/mcp.json`** mirrors repo **`.mcp.json`** (same servers; GitHub image pinned by **digest** for reproducibility). Cursor may also use user-level MCP settings — prefer the project file for team parity with Claude Code.
- **Bugbot:** `.cursor/BUGBOT.md` (if you use Cursor Bugbot).

## Claude Code (CLI / IDE extension)

- **Project config:** `.claude/settings.json` (hooks), `.claude/agents/`, `.claude/rules/`, `.claude/skills/`.
- **Local overrides (gitignored):** `.claude/settings.local.json` — machine-specific permissions or experiments.
- **Personal repo overrides:** `.claude.local.md` at repo root (gitignored) for preferences that should not be shared — see Anthropic [memory](https://code.claude.com/docs/en/memory) / team docs.

## Claude Desktop (Chat) and other Claude apps

Desktop does **not** automatically load repo-root `.mcp.json` the same way Claude Code does. Official flow:

- **Import Desktop MCP into Code:** `claude mcp add-from-claude-desktop` (see [Connect Claude Code to tools via MCP](https://docs.anthropic.com/en/docs/claude-code/mcp)).
- **Add Code-style MCP to Desktop:** use Desktop’s `claude_desktop_config.json` — mirror only the servers you need; keep secrets out of git.

**Cowork / Dispatch / team workflows:** product names and UIs change; treat them as **channels** where the same rules apply: issue-driven work, no secrets in threads, and vault + `AGENTS.md` for durable decisions. Link PRs and Issues from chat when a decision affects the codebase.

## MCP summary

| Location | Typical use |
|----------|-------------|
| Repo `.mcp.json` | **Claude Code** project-scoped MCP (versioned, team-shared); GitHub server uses a **digest-pinned** Docker image |
| `.cursor/mcp.json` | **Cursor** project-scoped MCP mirror (keep in sync with `.mcp.json`) |
| `~/.claude.json` | User-level MCP for Claude Code |
| Desktop config file | **Claude Desktop** MCP |
| Cursor user/project MCP | Cursor’s MCP settings UI (optional override of project file) |

### When to add MCP

Add a server when **agents or humans need live tool access** to a system (database, browser, ticketing) that is not already covered by the repo defaults. Prefer **repo `.mcp.json`** for team-shared, versioned wiring; document new env vars in **`.env.example`**. Skip redundant servers (same capability twice) and keep secrets out of git — see [OPTIONAL_CAPABILITIES.md](OPTIONAL_CAPABILITIES.md) for optional stacks (DB, browser, cloud).

**Context7** and **GitHub** (official [GitHub MCP Server](https://github.com/github/github-mcp-server) via **Docker** in `.mcp.json`) are wired for Claude Code. Export **`GITHUB_PERSONAL_ACCESS_TOKEN`** before launch (never commit it) — see `.env.example`, [GITHUB_SETUP.md](GITHUB_SETUP.md), and skill **`new-project-setup`**. If you cannot use Docker, use the remote HTTP / `claude mcp add-json` options in GitHub’s [Claude install guide](https://github.com/github/github-mcp-server/blob/main/docs/installation-guides/install-claude.md). Add DB/browser tools per project (see [OPTIONAL_CAPABILITIES.md](OPTIONAL_CAPABILITIES.md)).
