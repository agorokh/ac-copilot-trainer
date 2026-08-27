# PARKED

Append-only register. No tracker status. No automation.

Do not file issues for parked findings. A parked finding returns only if it
fires in practice or the operator promotes it. A follow-up PR whose only
content is parked findings is forbidden (governance-hub#482).

One line per park or narrow. Helper:

```bash
python3 "${FLEET_GOVERNANCE_ROOT:-$HOME/.fleet-governance}/scripts/review_finding_verdict.py" \
  append --parked docs/PARKED.md --repo <owner/repo> --category <reason> \
  --path <path> --claim <claim> --evidence <url> [--removes <over-reach>]
```

## Entries
