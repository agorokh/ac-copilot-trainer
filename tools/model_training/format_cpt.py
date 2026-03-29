"""Continual pre-training (CPT) corpus formatting (deferred).

CPT uses raw code and docs with a CLM objective; this repo needs a curated text extractor
and mixing policy (general vs domain). See issue #26 and vault ADR ``local-reviewer-model``.
"""

from __future__ import annotations


def iter_cpt_documents(_repo_root: object, **_kwargs: object):
    """Reserved for CPT text chunks; not implemented in Phase 1.

    Raises:
        NotImplementedError: Always, until repo text extraction exists (issue #26).
    """
    raise NotImplementedError(
        "CPT formatting is not implemented yet. "
        "Requires repo text extraction and chunking policy; see issue #26."
    )


def main() -> None:
    """Block CPT CLI until ``iter_cpt_documents`` is implemented."""
    raise NotImplementedError(
        "CPT formatting is not implemented yet; see GitHub issue #26 Phase 2+."
    )


if __name__ == "__main__":
    main()
