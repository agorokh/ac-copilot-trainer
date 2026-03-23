---
name: ci-check
description: Run local CI parity checks via make ci-fast. Use before merge or when verifying agent changes.
disable-model-invocation: true
---

# CI Check

Run from repository root:

```bash
make ci-fast
```

If a target is not applicable (e.g., no Python yet), document the exception in the PR and update the Makefile intentionally — do not silently skip checks.
