"""Preference / DPO dataset formatting (deferred).

Needs labeled accepted vs dismissed review comments from the process miner and PR metadata.
Planned in GitHub issue #26 (Tier 3) after Tier 1+2 signal quality improves.
"""

from __future__ import annotations


def iter_dpo_records(_source_db: object, **_kwargs: object):
    """Reserved for DPO pairs (chosen vs rejected); not implemented in Phase 1.

    Raises:
        NotImplementedError: Always, until preference labels exist (issue #26).
    """
    raise NotImplementedError(
        "DPO formatting is not implemented yet. "
        "Requires preference labels (accepted vs dismissed comments); see issue #26."
    )


def main() -> None:
    """Block DPO CLI until ``iter_dpo_records`` is implemented."""
    raise NotImplementedError(
        "DPO formatting is not implemented yet; see GitHub issue #26 Phase 2+."
    )


if __name__ == "__main__":
    main()
