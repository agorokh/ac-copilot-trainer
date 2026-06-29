"""Curated car-setup catalog: register a setup as a first-class data-platform entity.

A *curated* setup (a version-controlled ``.ini`` under ``assets/setups/<carID>/<track>/``) is
parsed, fingerprinted with the **same canonical hash the live rig computes for a driven lap**, and
recorded in a JSONL catalog the coaching lakehouse can join. See
:mod:`tools.setup_catalog.registrar`.

Naming note: this is deliberately ``setup_catalog`` (not ``setup_library``) to avoid colliding with
``src/ac_copilot_trainer/modules/setup_library.lua``, which keys on setup NAME/path by design. The
catalog adds a *content* identity (the canonical hash) on top of that name identity.
"""

from __future__ import annotations

from tools.setup_catalog.registrar import (
    SetupRecord,
    canonical_hash,
    canonical_setup_string,
    catalog_join_sql,
    deploy_setup,
    djb2_8hex,
    load_registry,
    register_setup,
    tunable_hash,
)

__all__ = [
    "SetupRecord",
    "canonical_hash",
    "canonical_setup_string",
    "catalog_join_sql",
    "deploy_setup",
    "djb2_8hex",
    "load_registry",
    "register_setup",
    "tunable_hash",
]
