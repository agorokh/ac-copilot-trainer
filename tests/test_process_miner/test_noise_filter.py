"""Tests for bot noise stripping before clustering (#70)."""

from __future__ import annotations

from tools.process_miner.noise_filter import (
    cluster_looks_like_boilerplate,
    drop_process_chrome_comments,
    is_boilerplate_body,
    is_process_chrome_only,
    strip_html_and_noise_plaintext,
    text_for_clustering,
)
from tools.process_miner.schemas import CommentCluster, ReviewComment


def _mk_comment(body: str, cid: str = "c1") -> ReviewComment:
    return ReviewComment(id=cid, body=body, author="coderabbit[bot]", author_type="bot")


def test_strip_html_removes_tags() -> None:
    s = strip_html_and_noise_plaintext("<p>Hello <b>world</b></p>")
    assert "<" not in s
    assert "Hello" in s


def test_codex_limit_is_boilerplate() -> None:
    body = "You have reached your Codex usage limits. See https://chatgpt.com/codex/settings/usage."
    assert is_boilerplate_body(body)


def test_boilerplate_regex_hits_use_html_strip_only() -> None:
    """_BOILERPLATE_RES matches must not run on text that already had those patterns stripped."""
    body = (
        "Reviewed by [Cursor Bugbot] for this SHA.\n"
        "See https://cursor.com/docs/bugbot for configuration.\n" + ("substance filler " * 4)
    )
    assert is_boilerplate_body(body)


def test_noise_header_references_requires_word_token() -> None:
    import tools.process_miner.noise_filter as nf

    assert not nf._section_title_matches_hint_list(
        "crossreferences",
        nf._NOISE_HEADER_HINTS,
    )
    assert nf._section_title_matches_hint_list(
        "see references below",
        nf._NOISE_HEADER_HINTS,
    )


def test_substance_header_bug_not_inside_debugging_token() -> None:
    import tools.process_miner.noise_filter as nf

    assert not nf._section_title_matches_hint_list(
        "debugging session notes",
        nf._SUBSTANCE_HEADER_HINTS,
    )
    assert nf._section_title_matches_hint_list("bug", nf._SUBSTANCE_HEADER_HINTS)


def test_substance_from_review_structure() -> None:
    c = ReviewComment(
        id="1",
        body="<!-- noise -->",
        author="bot",
        author_type="bot",
        bot_name="coderabbit",
        review_structure={
            "Walkthrough": "ignore me",
            "Issues found": "The cache key ignores the batch id so stale data can be served.",
        },
    )
    t = text_for_clustering(c)
    assert "cache key" in t.lower()
    assert "walkthrough" not in t.lower()


def test_cluster_majority_boilerplate() -> None:
    boiler = "You have reached your Codex usage limits for code reviews."
    ok = "The subprocess call does not check return codes before parsing stdout."
    comments = [
        ReviewComment(
            id=str(i),
            body=boiler if i < 2 else ok,
            author="b",
            author_type="bot",
            bot_name="x",
        )
        for i in range(3)
    ]
    cl = CommentCluster(
        cluster_id=0,
        title="t",
        count=3,
        comments=comments,
        affected_files=[],
        severity="nit",
        preventability="guideline",
        distinct_pr_count=2,
    )
    assert cluster_looks_like_boilerplate(cl)


# ---------- Pre-cluster process-chrome drop tests (#81) ----------


def test_process_chrome_actionable_count_dropped() -> None:
    # Exact pattern that dominated the Apr 2026 alpaca_trading run
    assert is_process_chrome_only("**Actionable comments posted: 3**")
    assert is_process_chrome_only("Actionable comments posted: 1")


def test_process_chrome_no_actionable_comments_dropped() -> None:
    body = (
        "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->\n"
        "No actionable comments were generated in the recent review."
    )
    assert is_process_chrome_only(body)


def test_process_chrome_reviewed_n_of_m_files_dropped() -> None:
    body = (
        "## Pull request overview\n\nCopilot reviewed 13 out of 13 changed files "
        "in this pull request and generated 1 comment."
    )
    assert is_process_chrome_only(body)


def test_process_chrome_reviews_paused_dropped() -> None:
    body = "> [!NOTE]\n> ## Reviews paused\n>\n> It looks like this PR is in draft state."
    assert is_process_chrome_only(body)


def test_process_chrome_rate_limit_dropped() -> None:
    assert is_process_chrome_only("Rate limit exceeded, try again later.")


def test_process_chrome_review_triggered_dropped() -> None:
    assert is_process_chrome_only("`@agorokh` Sure, I'll review the changes in this PR now!")
    assert is_process_chrome_only("Review triggered.")
    assert is_process_chrome_only("Actions performed: summary\nreview triggered")


def test_process_chrome_substantive_code_review_triggered_not_chrome() -> None:
    assert not is_process_chrome_only("The code review triggered a regression in the payment flow.")


def test_process_chrome_trial_promo_dropped() -> None:
    body = "Your Sourcery trial has expired. Upgrade to Sourcery Pro to continue receiving reviews."
    assert is_process_chrome_only(body)


def test_process_chrome_codex_usage_limit_real_phrasing_dropped() -> None:
    # The real ChatGPT Codex / Codex connector message. The first-pass regex had its
    # word order reversed ("limits have/are/reached"); Bugbot #81 review caught it.
    body = "You have reached your Codex usage limits. See https://chatgpt.com/codex/settings/usage."
    assert is_process_chrome_only(body)


def test_bot_name_alt_lists_are_disjoint_subsets_of_canon() -> None:
    import tools.process_miner.noise_filter as nf

    assert nf._WELCOME_BOTS <= nf._CHROME_BOT_NAMES
    assert nf._TRIGGER_BOTS <= nf._CHROME_BOT_NAMES
    # Verify the alternation helper actually emits sorted alternatives (stable pattern)
    alt = nf._bot_name_alt(include=nf._WELCOME_BOTS)
    assert alt.startswith("(?:")
    assert alt.endswith(")")
    inner = alt[3:-1]
    parts = inner.split("|")
    assert parts == sorted(parts)


def test_real_security_finding_is_NOT_chrome() -> None:
    # The kill-switch fallback finding from PR #751 — must survive the filter.
    body = (
        "When `AllocationPolicyResolver().resolve(bot_id)` raises `ValueError`, `allocation` "
        "(and `starting_equity`) falls back to `0.0`. With `allocation = 0.0`, `daily_loss_pct` "
        "becomes `0`, so the daily loss circuit breaker never triggers regardless of losses."
    )
    assert not is_process_chrome_only(body)


def test_real_silent_except_finding_is_NOT_chrome() -> None:
    body = (
        "The live-mode banner injection is wrapped in a broad `except Exception: pass`, "
        "which will silently hide real failures (including regressions in `inject_live_banner()`), "
        "making live UI issues hard to diagnose."
    )
    assert not is_process_chrome_only(body)


def test_real_shell_injection_finding_is_NOT_chrome() -> None:
    body = (
        "`LIVE_DB` is interpolated directly into a `CREATE DATABASE` SQL statement. If "
        "`DB_NAME_LIVE` contains unexpected characters (spaces, quotes, semicolons), this "
        "can break the script or allow SQL injection."
    )
    assert not is_process_chrome_only(body)


def test_empty_and_tiny_bodies_are_chrome() -> None:
    assert is_process_chrome_only("")
    assert is_process_chrome_only("   ")
    assert is_process_chrome_only("ok")


def test_drop_process_chrome_keeps_signal_and_counts_drops() -> None:
    comments = [
        _mk_comment("Actionable comments posted: 1", cid="a"),
        _mk_comment(
            "Silent exception swallowing loses diagnostic information; catch specific types.",
            cid="b",
        ),
        _mk_comment("No actionable comments were generated in the recent review.", cid="c"),
        _mk_comment(
            "The `except ValueError` only catches the 'bot not found' case; broader DB errors "
            "still propagate and mask allocation failures.",
            cid="d",
        ),
    ]
    kept, dropped = drop_process_chrome_comments(comments)
    assert dropped == 2
    assert len(kept) == 2
    kept_ids = {c.id for c in kept}
    assert kept_ids == {"b", "d"}


# Additional coverage for trigger-style and remaining markers (Sourcery #81 #11)


def test_process_chrome_at_trigger_coderabbitai_dropped() -> None:
    assert is_process_chrome_only("@coderabbitai review")


def test_process_chrome_at_trigger_copilot_dropped() -> None:
    assert is_process_chrome_only("@copilot review this PR")


def test_substantive_comment_after_bot_mention_not_chrome() -> None:
    """Do not treat @-mention + real question as a one-line trigger (Sourcery #81)."""
    body = "@coderabbit please clarify the error handling here — should we retry on 429?"
    assert not is_process_chrome_only(body)


def test_long_comment_with_review_now_phrase_not_chrome() -> None:
    """``review … now`` bot-ack pattern applies only to short bodies (Bugbot #81)."""
    body = (
        "I'll fix the allocation logic in the next commit; please review the retry path "
        "now that we've added exponential backoff around the Alpaca websocket reconnect."
    )
    assert not is_process_chrome_only(body)


def test_process_chrome_welcome_to_cursor_dropped() -> None:
    assert is_process_chrome_only("Welcome to Cursor Bugbot! Here's how to configure me.")


def test_process_chrome_persistent_review_updated_dropped() -> None:
    body = (
        "**Persistent review** updated to latest commit "
        "https://github.com/agorokh/template-repo/commit/abc123"
    )
    assert is_process_chrome_only(body)


def test_process_chrome_vault_handoff_line_dropped() -> None:
    assert is_process_chrome_only("Vault handoff line updated for PR #79.")


def test_process_chrome_post_merge_follow_ups_dropped() -> None:
    assert is_process_chrome_only("## Post-merge follow-ups\n\n- scripts/ changed")


def test_rate_limit_technical_discussion_is_NOT_chrome() -> None:
    body = (
        "The rate limit for the Alpaca API is 200 requests per minute. "
        "We should add backoff logic in the retry handler."
    )
    assert not is_process_chrome_only(body)
