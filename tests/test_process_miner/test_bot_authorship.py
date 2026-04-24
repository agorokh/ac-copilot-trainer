"""Bot authorship helpers (#56)."""

from __future__ import annotations

import json

import pytest

from tools.process_miner.bot_authorship import (
    BOT_LOGIN_ALIASES,
    BOT_REVIEW_TEXT_CLIP_CHARS,
    bot_agreement_location_key,
    clear_merged_bot_aliases_cache,
    infer_author_from_user,
    normalize_bot_canonical_name,
    parse_review_structure,
)


def test_infer_human_user() -> None:
    login, at, bn = infer_author_from_user({"login": "alice", "type": "User"})
    assert login == "alice"
    assert at == "human"
    assert bn is None


def test_infer_known_bot() -> None:
    login, at, bn = infer_author_from_user({"login": "coderabbitai", "type": "Bot"})
    assert login == "coderabbitai"
    assert at == "bot"
    assert bn == "coderabbit"


def test_infer_unknown_bot_slug() -> None:
    _login, at, bn = infer_author_from_user({"login": "my-custom-bot[bot]", "type": "Bot"})
    assert at == "bot"
    assert bn == "my_custom_bot_bot"


def test_infer_missing_user_is_unknown_not_human() -> None:
    login, at, bn = infer_author_from_user(None)
    assert login == "unknown"
    assert at == "unknown"
    assert bn is None


def test_infer_alias_login_treated_as_bot_when_type_user() -> None:
    """Some integrations use a User-typed account with a known bot login."""
    login, at, bn = infer_author_from_user({"login": "coderabbitai", "type": "User"})
    assert login == "coderabbitai"
    assert at == "bot"
    assert bn == "coderabbit"


def test_process_miner_bot_aliases_json_warns_on_invalid_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_merged_bot_aliases_cache()
    monkeypatch.setenv(
        "PROCESS_MINER_BOT_ALIASES_JSON",
        json.dumps({"good-bot": "gb", "bad": 1, "": "x"}),
    )
    with pytest.warns(UserWarning, match="ignored 2 invalid"):
        _login, at, bn = infer_author_from_user({"login": "good-bot", "type": "Bot"})
    assert at == "bot"
    assert bn == "gb"
    clear_merged_bot_aliases_cache()


def test_normalize_bot_canonical_name_matches_unknown_bot_slug_rule() -> None:
    assert normalize_bot_canonical_name("Review Bot") == "review_bot"
    assert normalize_bot_canonical_name("  review_bot  ") == "review_bot"


def test_process_miner_bot_aliases_json_env_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_merged_bot_aliases_cache()
    monkeypatch.setenv(
        "PROCESS_MINER_BOT_ALIASES_JSON",
        json.dumps({"myorg-review-bot": "reviewbot"}),
    )
    _login, at, bn = infer_author_from_user({"login": "myorg-review-bot", "type": "Bot"})
    assert at == "bot"
    assert bn == "reviewbot"
    _login2, at2, bn2 = infer_author_from_user({"login": "coderabbitai", "type": "Bot"})
    assert at2 == "bot"
    assert bn2 == "coderabbit"
    clear_merged_bot_aliases_cache()


def test_process_miner_bot_aliases_json_normalizes_value_whitespace_and_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_merged_bot_aliases_cache()
    monkeypatch.setenv(
        "PROCESS_MINER_BOT_ALIASES_JSON",
        json.dumps({"myorg-review-bot": "Review Bot"}),
    )
    _login, at, bn = infer_author_from_user({"login": "myorg-review-bot", "type": "Bot"})
    assert at == "bot"
    assert bn == "review_bot"
    clear_merged_bot_aliases_cache()


def test_parse_review_structure_sections() -> None:
    body = "## Summary\n\nHello\n\n## Walkthrough\n\nDetails here"
    struct = parse_review_structure(body, "bot", "coderabbit")
    assert struct is not None
    assert "Summary" in struct
    assert "Walkthrough" in struct


def test_parse_review_structure_returns_none_for_non_bot() -> None:
    body = "## Summary\n\nHello"
    assert parse_review_structure(body, "human", None) is None


def test_parse_review_structure_clips_long_sections() -> None:
    long_chunk = "x" * (BOT_REVIEW_TEXT_CLIP_CHARS + 50)
    body = f"## Big\n\n{long_chunk}"
    struct = parse_review_structure(body, "bot", "gemini")
    assert struct is not None
    assert len(struct["Big"]) == BOT_REVIEW_TEXT_CLIP_CHARS


def test_parse_review_structure_skips_headers_inside_fenced_code() -> None:
    body = "## Real\n\nintro\n\n```bash\n## not a section\nx=1\n```\n\n## After\n\nok"
    struct = parse_review_structure(body, "bot", "gemini")
    assert struct is not None
    assert set(struct.keys()) == {"Real", "After"}
    assert "not a section" not in struct["Real"]


def test_bot_aliases_cover_documented_reviewers() -> None:
    assert BOT_LOGIN_ALIASES["gemini-code-assist"] == "gemini"
    assert BOT_LOGIN_ALIASES["gemini-code-assist[bot]"] == "gemini"
    assert BOT_LOGIN_ALIASES["sourcery-ai"] == "sourcery"


def test_bot_agreement_location_key_inline_vs_file_vs_thread() -> None:
    assert bot_agreement_location_key(path="a.py", line=3, comment_id="c1") == "inline:a.py:3"
    assert bot_agreement_location_key(path="a.py", line=None, comment_id="c2") == "file:a.py:id:c2"
    assert bot_agreement_location_key(path=None, line=None, comment_id="c3") == "thread:c3"
