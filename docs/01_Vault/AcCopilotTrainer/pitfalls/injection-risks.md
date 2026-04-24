---
type: pitfall
status: active
created: 2026-04-10
updated: 2026-04-10
severity: security
scope_paths:
  - "scripts/**"
  - ".github/workflows/**"
  - "**/pipeline/**"
  - "src/**"
domains: [trading, legal, infra]
canonical_prs:
  - repo: agorokh/template-repo
    prs: [58, 57]
    note: Workflow dispatch input directly interpolated into shell script
  - repo: agorokh/disclosures-discovery
    prs: [135]
    note: Per-row SQL query uses string interpolation -- breaks on quotes, injection risk
relates_to:
  - AcCopilotTrainer/00_System/invariants/no-secrets.md
  - AcCopilotTrainer/pitfalls/missing-input-validation.md
  - AcCopilotTrainer/pitfalls/_index.md
---

# Injection risks (SQL + shell)

**2 clusters, 9 comments, 2 repos** (template-repo, disclosures-discovery)

## Pattern

String interpolation (f-strings, `.format()`, `%s`) used to build SQL queries or shell commands instead of parameterized APIs. The implementing agent writes the quick path because it works for clean inputs, but production data contains quotes, semicolons, or special characters that break or exploit the query.

Two variants:
- **SQL injection:** `f"SELECT * FROM t WHERE name = '{user_input}'"` instead of parameterized `?`
- **Shell injection:** `os.execute("mkdir " .. path)` or `subprocess.run(f"cmd {input}", shell=True)` instead of list args

## Preventive rule

1. **SQL:** Always use parameterized queries (`cursor.execute("SELECT ... WHERE x = ?", (val,))`). Never concatenate user input into SQL strings.
2. **Shell:** Always use `subprocess.run([cmd, arg1, arg2], check=True)` with list args. Never use `shell=True` with external input. In Lua, validate paths against an allowlist before passing to `os.execute` or `io.popen` — Lua has no built-in shell escaping, so path validation is the only safe approach.
3. **GitHub Actions:** Never interpolate `${{ github.event.inputs.* }}` or `${{ steps.*.outputs.* }}` directly into `run:` blocks. Use environment variables: `env: INPUT: ${{ github.event.inputs.value }}` then `"$INPUT"` in the script.

## Canonical damage

In `template-repo` PR #58, a workflow dispatch input (`days`) was directly interpolated into a shell `run:` block. A malicious dispatch could inject arbitrary commands. Fix: pass via `env:` and quote the variable.
