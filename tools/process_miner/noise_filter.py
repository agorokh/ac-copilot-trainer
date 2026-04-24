"""Strip bot boilerplate before clustering and gate rule emission (#70, #78, semantic).

Three filtering layers compose in this module:

1. **Pre-cluster drops** (``is_process_chrome_only``) — whole comments that are pure
   process notifications (``Actionable comments posted: N``, ``Reviewed X of Y files``,
   ``No actionable comments``, ``Reviews paused``). Dropped from the clustering pool so
   TF-IDF / semantic clustering never sees them.
2. **Per-comment text cleanup** (``text_for_clustering``, ``strip_html_and_noise_plaintext``)
   — remove HTML tags, severity badges, trial chrome, etc. from comments that *do* carry
   a substantive signal.
3. **Post-cluster cleanup** (``post_cluster_cleanup``) — merge near-duplicate titles and
   drop clusters whose *titles* are themselves bot product names.
"""

from __future__ import annotations

import re
from typing import Any

from tools.process_miner.schemas import CommentCluster, ReviewComment

# Section titles (lowercase) whose bodies we prefer for structured bot reviews.
_SUBSTANCE_HEADER_HINTS: frozenset[str] = frozenset(
    {
        "issue",
        "issues",
        "description",
        "summary",
        "overview",
        "feedback",
        "findings",
        "action required",
        "action items",
        "review",
        "suggestion",
        "nitpick",
        "bug",
        "security",
    }
)

# Section titles to drop (noise / chrome). Avoid bare "tools" — substring hits real sections
# like "Debugging tools overview" (Bugbot #75).
_NOISE_HEADER_HINTS: frozenset[str] = frozenset(
    {
        "prompt for ai agents",
        "prompt for ai agent",
        "walkthrough",
        "references",
        "additional locations",
        "fingerprinting",
        "example commits",
        "example code",
        "diagram walkthrough",
        "sequence diagram",
    }
)

# Configurable boilerplate patterns. Use DOTALL only for HTML comments that may span lines;
# line-local phrases use IGNORECASE alone so greedy ``.*`` cannot swallow whole documents.
_I = re.IGNORECASE
_S = re.DOTALL
_BOILERPLATE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"<!--\s*fingerprinting:.*?-->", _I | _S),
    re.compile(r"<!--\s*This is an auto-generated comment.*?-->", _I | _S),
    re.compile(r"codex usage dashboard", _I),
    re.compile(r"trial.*?expir", _I),
    re.compile(r"sourcery.*?trial", _I),
    re.compile(r"upgrade to sourcery", _I),
    re.compile(r"no actionable comments", _I),
    re.compile(r"_\s*⚠️\s*Potential issue_", _I),
    re.compile(r"_\s*🟡\s*Minor_", _I),
    re.compile(r"_\s*🟠\s*Major_", _I),
    re.compile(r"_\s*🔵\s*Trivial_", _I),
    re.compile(r"https://www\.qodo\.ai/", _I),
    re.compile(r"https://cursor\.com/docs", _I),
    re.compile(r"Reviewed by \[Cursor Bugbot\]", _I),
    re.compile(r"Triggered by project rule:", _I),
    re.compile(r"\[!\[[^\]]*\]\([^\)]*\)\]", _I),  # badge images
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Cluster *titles* are top TF-IDF tokens (often bot / product names permuted). #78
_TITLE_CHROME_WORDS: frozenset[str] = frozenset(
    {
        "reviewed",
        "cursor",
        "bugbot",
        "github",
        "comments",
        "copilot",
        "coderabbit",
        "sourcery",
        "gemini",
        "qodo",
        "auto",
        "generated",
        "review",
        "pull",
        "request",
        "code",
        "assist",
        "anthropic",
        "openai",
    }
)

_TITLE_CHROME_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(coderabbit|sourcery|bugbot|copilot)\b", _I),
    re.compile(r"\b(auto[- ]generated|usage limits?)\b", _I),
)


def _section_title_matches_hint_list(title: str, hints: frozenset[str]) -> bool:
    """Match multi-word hints as substrings; single-token hints as whole words (not substrings)."""
    tl = title.strip().lower()
    for raw in hints:
        h = raw.strip().lower()
        if not h:
            continue
        if " " in h:
            if h in tl:
                return True
        elif re.search(rf"(?<![\w]){re.escape(h)}(?![\w])", tl):
            return True
    return False


def strip_html_and_noise_plaintext(text: str) -> str:
    """Remove HTML tags and apply boilerplate regex drops."""
    t = _HTML_TAG_RE.sub(" ", text or "")
    for rx in _BOILERPLATE_RES:
        t = rx.sub(" ", t)
    return t


def _substance_from_review_structure(struct: dict[str, str] | None) -> str | None:
    if not struct:
        return None
    parts: list[str] = []
    for title, body in struct.items():
        tl = title.strip().lower()
        if _section_title_matches_hint_list(tl, _NOISE_HEADER_HINTS):
            continue
        if (
            not _section_title_matches_hint_list(tl, _SUBSTANCE_HEADER_HINTS)
            and len(tl) > 40
            and len(body.strip()) < 80
        ):
            continue
        b = strip_html_and_noise_plaintext(body).strip()
        if len(b) >= 40:
            parts.append(b)
    if not parts:
        return None
    return "\n\n".join(parts)


def text_for_clustering(comment: ReviewComment) -> str:
    """Body text fed into TF-IDF: structured sections when present, else stripped plain body."""
    sub = _substance_from_review_structure(comment.review_structure)
    if sub is not None:
        return sub.strip()
    return strip_html_and_noise_plaintext(comment.body or "").strip()


def is_boilerplate_body(text: str) -> bool:
    """Heuristic: comment is mostly bot chrome / trials / empty signal.

    Length uses fully stripped text ``t``; regex and phrase hits use ``html_plain`` (tags removed,
    but ``_BOILERPLATE_RES`` not yet applied) so multi-signal thresholds stay meaningful.
    """
    raw = text or ""
    t = strip_html_and_noise_plaintext(raw).lower()
    if len(t) < 30:
        return True
    # Regex hits must run on text that has *not* already had _BOILERPLATE_RES applied
    # (strip_html_and_noise_plaintext removes those matches, which would zero out hits).
    html_plain = _HTML_TAG_RE.sub(" ", raw).lower()
    if re.search(r"codex\s+usage\s+limits?", html_plain):
        return True
    hits = sum(1 for rx in _BOILERPLATE_RES if rx.search(html_plain))
    need = 3 if len(t) >= 120 else 2
    if hits >= need:
        return True
    noise_phrases = (
        "auto-generated comment",
        "language tool",
        "potential issue",
        "nitpick",
        "changelog maintenance",
        "commits without user",
    )
    return sum(1 for p in noise_phrases if p in html_plain) >= 3


def cluster_looks_like_boilerplate(cluster: CommentCluster) -> bool:
    """True if a majority of comments look like boilerplate."""
    if not cluster.comments:
        return True
    bad = sum(1 for c in cluster.comments if is_boilerplate_body(c.body))
    return bad > len(cluster.comments) // 2


# Canonical bot name registry — single source of truth for any regex that lists bot
# identities. Keeping all chrome patterns derived from this set makes it easy to add a
# new reviewer without drifting definitions across markers and triggers (Gemini #81
# review feedback).
_CHROME_BOT_NAMES: frozenset[str] = frozenset(
    {
        "coderabbit",
        "coderabbitai",
        "codexbot",
        "copilot",
        "cursor",
        "bugbot",
        "sourcery",
        "qodo",
        "gemini",
    }
)


def _bot_name_alt(*, include: frozenset[str] | None = None) -> str:
    """Return a regex alternation ``(?:a|b|c)`` over the canonical bot name set.

    ``include`` lets callers narrow the alternation when only a subset applies (e.g. the
    "welcome to ..." greeting matches product-named bots but not CLI trigger aliases).
    Names are sorted for a stable, test-friendly pattern.
    """
    names = _CHROME_BOT_NAMES if include is None else (include & _CHROME_BOT_NAMES)
    if not names:
        raise ValueError("bot name alternation requires at least one name")
    return "(?:" + "|".join(sorted(names)) + ")"


_WELCOME_BOTS: frozenset[str] = frozenset({"cursor", "bugbot", "coderabbit", "sourcery", "qodo"})
_TRIGGER_BOTS: frozenset[str] = frozenset(
    {"coderabbit", "coderabbitai", "codexbot", "copilot", "sourcery", "qodo", "gemini"}
)


# Phrase markers that identify comments as *pure* process notifications — no technical
# content at all. Used by ``is_process_chrome_only`` to drop comments before clustering.
# Each phrase must be distinctive enough that any match means the comment is chrome.
_PROCESS_CHROME_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bactionable\s+comments?\s+posted\s*:", _I),
    re.compile(r"no\s+actionable\s+comments?\s+(?:were|have\s+been)\s+generated", _I),
    re.compile(r"reviewed\s+\d+\s+out\s+of\s+\d+\s+changed\s+files", _I),
    re.compile(r"review(?:s)?\s+paused", _I),
    # Narrowed to bot-context: require "rate limit" adjacent to review/API language,
    # not just any mention (could be a legitimate discussion about rate limiting as a feature).
    re.compile(r"rate\s*limit\s+(?:exceeded|reached|hit).{0,40}?(?:try|later|again|wait)", _I),
    # Real phrasing is "You have reached your Codex usage limits" — match the sentence
    # shape with ``reached`` *before* the noun phrase, not after it (Bugbot #81 review).
    re.compile(r"reached\s+(?:your|the)\s+codex\s+usage\s+limits?", _I),
    # Bot chrome: either the line *starts* with "review triggered", or it follows
    # "actions performed" (GitHub bot summary). Do not use ``^.{0,30}?review`` — that
    # false-positives on "The code review triggered …" (Bugbot #81).
    re.compile(
        r"(?:^review\s+triggered\.?|\bactions?\s+performed\b.{0,40}?review\s+triggered\.?)", _I
    ),
    re.compile(r"trial\s+(?:has|is).{0,15}?(?:expir|end)", _I),
    re.compile(r"upgrade\s+to\s+sourcery", _I),
    re.compile(rf"\bwelcome\s+to\s+{_bot_name_alt(include=_WELCOME_BOTS)}", _I),
    re.compile(r"\bpersistent\s+review.{0,80}?updated\s+to\s+latest\s+commit", _I),
    re.compile(r"vault\s+handoff\s+line\s+updated\s+for\s+pr", _I),
    re.compile(r"post[- ]merge\s+follow[- ]ups?", _I),  # auto-post by steward
)

# Short standalone commands/triggers that produce no signal: drop when comment is
# basically a one-liner like "@coderabbitai review" with no body.  The command token
# must be a known low-signal verb so "@coderabbit please clarify …" stays in the pool
# (Sourcery #81).
_TRIGGER_COMMAND_VERB = (
    r"(?:review|rerun|recheck|analyze|analysis|check|checks?|run|invoke|resume|start|pause|"
    r"ignore|lint|format|summarize|summarise)\b"
)
_PROCESS_CHROME_TRIGGERS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"^@{_bot_name_alt(include=_TRIGGER_BOTS)}[\w-]*\s+{_TRIGGER_COMMAND_VERB}",
        _I,
    ),
)

# Bot ack "I'll/sure … review … now" — only for *short* bodies so long engineering
# comments that mention reviewing are not dropped (Bugbot #81).
_REVIEW_NOW_BOT_ACK = re.compile(
    r"(?:i(?:'ll|\s+will)|sure[,!])\s*.{0,50}?review.{0,40}?\bnow\b",
    _I,
)


def is_process_chrome_only(text: str) -> bool:
    """Pre-cluster gate: drop comments that are *only* process notifications.

    This is stricter than :func:`is_boilerplate_body`: here we look for *high-precision*
    phrase markers that unambiguously identify the comment as bot admin chrome (review
    paused, rate-limit hit, actionable-count summary, trial promo, etc.). Any match →
    drop the whole comment from the clustering pool.

    Rationale: clustering these produces "universal patterns" like ``code / lgtm / with``
    that carry zero engineering signal. The user's feedback (2026-04): *"I reviewed this
    PR and find no comments — that's literally no comments pattern. We probably need to
    drop it."* (see #81, semantic clustering proposal.)
    """
    raw = text or ""
    if not raw.strip():
        return True
    plain = _HTML_TAG_RE.sub(" ", raw)
    # Collapse whitespace and strip markdown chrome for phrase matching
    collapsed = re.sub(r"\s+", " ", plain).strip()
    if len(collapsed) < 5:
        return True
    # Short comment that is exactly a trigger or bot "review now" ack → drop
    if len(collapsed) < 120:
        for rx in _PROCESS_CHROME_TRIGGERS:
            if rx.search(collapsed):
                return True
        if _REVIEW_NOW_BOT_ACK.search(collapsed):
            return True
    # High-precision phrase markers → drop regardless of length
    return any(rx.search(collapsed) for rx in _PROCESS_CHROME_MARKERS)


def drop_process_chrome_comments(
    comments: list[ReviewComment],
) -> tuple[list[ReviewComment], int]:
    """Return ``(kept, dropped_count)`` after stripping pre-cluster process chrome.

    Keeps comments whose body carries any technical substance; drops comments identified
    by :func:`is_process_chrome_only`. This runs *before* TF-IDF / semantic clustering so
    the filtered-out chrome never influences vectorization or centroid math.
    """
    kept = [c for c in comments if not is_process_chrome_only(c.body or "")]
    return kept, len(comments) - len(kept)


def normalize_cluster_title_dedup_key(title: str) -> str:
    """Order-independent key so permuted TF-IDF titles (``a / b / c`` vs ``c / a / b``) merge."""
    raw = (title or "").strip()
    t = _HTML_TAG_RE.sub(" ", raw).lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Do not merge distinct TF-IDF fallbacks ``Cluster 0`` / ``Cluster 1`` into one bucket.
    if re.fullmatch(r"cluster \d+", t):
        return t
    tokens = [w for w in t.split() if w]
    # Prefer tokens with len>=3 to reduce noise from tiny glue words; if that leaves too
    # little signal, include len>=2 so short technical tokens (``go``, ``js``, ``io``)
    # still distinguish otherwise-similar titles (Bugbot / Gemini #78).
    words_long = sorted({w for w in tokens if len(w) >= 3})
    if len(words_long) >= 2:
        return " ".join(words_long)
    words_med = sorted({w for w in tokens if len(w) >= 2})
    if words_med:
        return " ".join(words_med)
    words_all = sorted(set(tokens))
    return " ".join(words_all) if words_all else t


def cluster_title_is_bot_chrome(title: str) -> bool:
    """Heuristic: cluster *title* is mostly reviewer/bot product chrome, not substance."""
    plain = strip_html_and_noise_plaintext(title or "").strip()
    tl = plain.lower()
    if len(tl) < 3:
        return True
    for rx in _TITLE_CHROME_RES:
        if rx.search(tl):
            return True
    words = set(re.findall(r"\b\w+\b", tl))
    if not words:
        return True
    if words <= _TITLE_CHROME_WORDS:
        return True
    chrome_hits = sum(1 for w in words if w in _TITLE_CHROME_WORDS)
    if len(words) == 1:
        return False
    if len(words) == 2:
        return chrome_hits >= 2
    return chrome_hits >= len(words) - 1 and chrome_hits >= 2


def _collect_representative_examples(clusters: list[CommentCluster], limit: int = 6) -> list[str]:
    out: list[str] = []
    for cl in clusters:
        for ex in cl.representative_examples:
            if ex and ex not in out:
                out.append(ex)
            if len(out) >= limit:
                return out
    return out


def _merge_cluster_group(group: list[CommentCluster]) -> CommentCluster:
    """Merge clusters sharing the same title dedup key (runtime import avoids analyze cycle).

    ``cluster_id`` is assigned later by ``post_cluster_cleanup`` after sorting.
    """
    from tools.process_miner.analyze import (  # noqa: PLC0415 — avoid import cycle at module level
        _dominant_cluster_author_type,
        _dominant_cluster_bot_name,
        more_consequential_preventability,
        more_severe_severity,
    )

    group = sorted(group, key=lambda c: (-c.count, -c.distinct_pr_count, c.title))
    best = group[0]
    seen_ids: set[str] = set()
    all_comments: list[ReviewComment] = []
    for cl in group:
        for c in cl.comments:
            if c.id not in seen_ids:
                seen_ids.add(c.id)
                all_comments.append(c)
    file_order: list[str] = []
    seen_paths: set[str] = set()
    for cl in group:
        for p in cl.affected_files:
            if p not in seen_paths:
                seen_paths.add(p)
                file_order.append(p)
    pr_nums = {c.pr_number for c in all_comments if c.pr_number is not None}
    examples = _collect_representative_examples(group, 6)

    severity = "nit"
    preventability = "guideline"
    for cl in group:
        severity = more_severe_severity(severity, cl.severity)
        preventability = more_consequential_preventability(preventability, cl.preventability)
    dom_author = _dominant_cluster_author_type(all_comments)
    dom_bot = _dominant_cluster_bot_name(all_comments) if dom_author == "bot" else None
    return CommentCluster(
        cluster_id=0,
        title=best.title,
        count=len(all_comments),
        comments=all_comments,
        affected_files=file_order[:5],
        severity=severity,
        preventability=preventability,
        representative_examples=examples[:6],
        dominant_author_type=dom_author,
        dominant_bot_name=dom_bot,
        distinct_pr_count=len(pr_nums),
    )


def post_cluster_cleanup(
    clusters: list[CommentCluster],
) -> tuple[list[CommentCluster], dict[str, Any]]:
    """Near-duplicate title merge, then drop bot-chrome titles; return audit dict (#78)."""
    if not clusters:
        return [], {"near_duplicate_merges": [], "dropped_title_bot_chrome": []}

    from collections import defaultdict

    merges_audit: list[dict[str, Any]] = []
    by_key: dict[str, list[CommentCluster]] = defaultdict(list)
    for cl in clusters:
        by_key[normalize_cluster_title_dedup_key(cl.title)].append(cl)

    merged: list[CommentCluster] = []
    for _key, group in sorted(by_key.items(), key=lambda kv: (-sum(c.count for c in kv[1]), kv[0])):
        if len(group) == 1:
            merged.append(group[0])
        else:
            titles = [g.title for g in group]
            n_before = sum(len(g.comments) for g in group)
            mc = _merge_cluster_group(group)
            merges_audit.append(
                {
                    "dedup_key": _key,
                    "merged_titles": titles,
                    "into_title": mc.title,
                    "n_subclusters": len(group),
                    "n_comments_before": n_before,
                    "n_comments_after": len(mc.comments),
                }
            )
            merged.append(mc)

    dropped_audit: list[dict[str, Any]] = []
    kept: list[CommentCluster] = []
    for cl in merged:
        if cluster_title_is_bot_chrome(cl.title):
            dropped_audit.append(
                {
                    "title": cl.title,
                    "count": cl.count,
                    "distinct_prs": cl.distinct_pr_count,
                }
            )
        else:
            kept.append(cl)

    # Global ranking after merges: dedup buckets were ordered by bucket mass, not per-cluster count.
    kept.sort(key=lambda c: c.count, reverse=True)
    for i, cl in enumerate(kept):
        cl.cluster_id = i
        plain = (cl.title or "").strip()
        if re.fullmatch(r"(?i)cluster\s+\d+", plain):
            cl.title = f"Cluster {cl.cluster_id}"

    audit: dict[str, Any] = {
        "near_duplicate_merges": merges_audit,
        "dropped_title_bot_chrome": dropped_audit,
    }
    return kept, audit
