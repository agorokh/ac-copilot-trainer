"""Default fleet list and repo → domain tags for cross-repo mining (#70)."""

from __future__ import annotations

# owner/name → domain bucket (legal, trading, infra, gaming). Keys normalized to lowercase.
_REPO_DOMAIN_RAW: dict[str, str] = {
    "agorokh/template-repo": "infra",
    "agorokh/ac-copilot-trainer": "gaming",
    "agorokh/mcp-servers": "infra",
    "agorokh/disclosures-discovery": "legal",
    "agorokh/alpaca_trading": "trading",
    "agorokh/case_operations": "legal",
    "agorokh/court-fillings-processing": "legal",
    "agorokh/dial-sandbox": "infra",
    "agorokh/camera-poc": "infra",
    "agorokh/tesla-automation": "infra",
    "agorokh/stock_hero_helper": "trading",
    "agorokh/imessage-semantic-analysis": "infra",
    "agorokh/alpaca-mcp-server": "trading",
}
REPO_DOMAIN: dict[str, str] = {k.lower(): v for k, v in _REPO_DOMAIN_RAW.items()}

# Active + dormant repos from issue #70 (comma-join for MINING_REPOS).
DEFAULT_FLEET_REPOS: tuple[str, ...] = (
    "agorokh/template-repo",
    "agorokh/ac-copilot-trainer",
    "agorokh/mcp-servers",
    "agorokh/disclosures-discovery",
    "agorokh/alpaca_trading",
    "agorokh/case_operations",
    "agorokh/court-fillings-processing",
    "agorokh/dial-sandbox",
    "agorokh/camera-poc",
    "agorokh/tesla-automation",
    "agorokh/stock_hero_helper",
    "agorokh/imessage-semantic-analysis",
    "agorokh/alpaca-mcp-server",
)


def domain_for_repo(repo_slug: str) -> str | None:
    """Return domain tag or None if unknown."""
    key = repo_slug.strip().lower().replace(" ", "")
    return REPO_DOMAIN.get(key)
