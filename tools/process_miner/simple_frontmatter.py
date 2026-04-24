"""Shared best-effort YAML-ish frontmatter parsing for vault audit and knowledge ingest."""

from __future__ import annotations


def parse_simple_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse leading ``---`` block into scalar key/value pairs; skip list-item lines."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        meta[key.strip()] = val.strip().strip("\"'")
    return meta, body


def extract_relates_to(raw_frontmatter: str) -> list[str]:
    """Pull ``relates_to`` list entries from the first frontmatter block (best-effort)."""
    if not raw_frontmatter.startswith("---"):
        return []
    end = raw_frontmatter.find("\n---", 3)
    if end == -1:
        return []
    block = raw_frontmatter[3:end]
    out: list[str] = []
    in_relates = False
    for line in block.splitlines():
        s = line.strip()
        if s.startswith("relates_to:"):
            in_relates = True
            continue
        if in_relates:
            if s.startswith("- "):
                val = s[2:].strip().strip("\"'")
                if val:
                    out.append(val)
                continue
            if s and not s.startswith("#") and ":" in s and not s.startswith("-"):
                in_relates = False
    return out
