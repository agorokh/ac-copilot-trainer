# Hook design convention

**Status:** Core
**Applies to:** `.claude/settings.base.json` and child `.claude/settings.local.json` overlays.

Claude Code hooks have three shapes relevant here: **command**, **prompt**, and **agent**. They carry very different reliability guarantees. Mixing them up is how a template accumulates silent agent-stopping bugs (see template-repo #91 for a concrete example).

## Rule

| Hook purpose | Use | Why |
|--------------|-----|-----|
| **Flow control** — allow / block the tool call | **`type: "command"`** | Shell exit codes are deterministic. `exit 2` is a hard block that Claude Code understands unambiguously. |
| **Advisory nudge** — tell the agent something but do not gate the call | `type: "prompt"` is acceptable | The small model can be wrong about whether to reply `ALLOW` vs. `BLOCK`, but a soft reminder degrades gracefully. |
| **Verification** — inspect work after it is done | `type: "agent"` (or command) | Agent hooks are slow and run a sub-agent; keep them out of the per-tool hot path. |

### Concrete implications

1. **Never** put a `type: "prompt"` hook on `PostToolUse:Bash`. It will fire on every single bash call. Small-model output drift (different wording across model versions, verbose prose instead of a single token) silently halts continuation after every successful command. If you think you want this, you want the `learner` agent running post-merge instead.
2. **Never** use a prompt hook to enforce a security boundary (protected branch, sensitive file path, secret scanning with a blocking exit). If the rule is testable from the tool input alone (command string, file path), write a short shell script with `exit 0` / `exit 2` and a test.
3. Advisory prompt hooks that are *designed* to degrade gracefully (LOAD reminder, opt-in SQL DDL warning) are fine. Name them clearly and make sure "wrong reply" is not a security or correctness failure.

## Authoring checklist

When you add a flow-control hook:

- [ ] Write it as a `type: "command"` hook calling a script under `scripts/`.
- [ ] Extract tool input (`command`, `file_path`, etc.) with `python3 -c "..."` — `python3` is already a repo dep and avoids shelling out to `jq`.
- [ ] Fail open (`exit 0`) on malformed JSON or missing fields. Hooks must never wedge the agent on input they do not understand.
- [ ] Emit the reason on `stderr` before `exit 2` so the user sees why the call was blocked.
- [ ] Add cases to `tests/test_hook_scripts.py`: synthetic JSON in, expected exit code out. The test is the contract.

## Anti-pattern examples

**❌ Prompt hook for flow control.** Depends on the small model emitting `PASS`, `ALLOW`, or `BLOCK` exactly.

```json
{
  "matcher": "Bash",
  "hooks": [{
    "type": "prompt",
    "prompt": "If the bash command would commit or push to protected branch main/master, BLOCK. ... Reply BLOCK: <reason> or ALLOW."
  }]
}
```

**✅ Command hook.** Deterministic; exit code is the answer.

```json
{
  "matcher": "Bash",
  "hooks": [{
    "type": "command",
    "command": "bash \"${CLAUDE_PROJECT_DIR}/scripts/hook_protect_main.sh\"",
    "timeout": 5000
  }]
}
```

## See also

- `.claude/settings.base.json` — canonical hook definitions.
- `scripts/merge_settings.py` — produces `settings.json` from base + local overlay.
- `tests/test_hook_scripts.py` — smoke tests for hook scripts.
- `docs/00_Core/MAINTAINING_THE_TEMPLATE.md` — changelog for governance-facing hook changes.
