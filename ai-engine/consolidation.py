"""Consolidation: turn a finished day's raw traces and activity into episodes
and a day summary (ADR 0013).

An episode is a stretch of related work: time-contiguous activity, split by
long gaps, very long blocks or a clear change of topic. Each gets a short
title and a one-to-three sentence summary written by the local model from
its traces, citing them. The day summary is written from the episodes,
citing them. Numbers (times, durations, apps) are computed by code.

Consolidation is idempotent: running it again for a day replaces that day's
episodes and summary.
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import db
import store
from exclusions import is_system_process

GAP_SECONDS = 20 * 60          # a pause longer than this starts a new episode
MAX_EPISODE_SECONDS = 3 * 3600  # no episode longer than this
MIN_EPISODE_SECONDS = 3 * 60    # shorter episodes without memories are noise
TOPIC_SPLIT = 0.08              # word overlap below this, on a new app, is a new topic
MIN_SPLIT_SECONDS = 10 * 60     # ...but only for a session long enough to matter
EPISODE_SOURCES = 6
EPISODE_SOURCE_CHARS = 600

_WORD = re.compile(r"[a-z][a-z0-9]{2,}")
_CITATION = re.compile(r"\[\d+\]")
_COMMON = {"the", "and", "for", "with", "this", "that", "from", "google", "chrome", "untitled", "new", "tab"}


def words_of(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _COMMON}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


@dataclass
class Episode:
    start: datetime
    end: datetime
    apps: dict[str, float] = field(default_factory=dict)
    titles: list[str] = field(default_factory=list)
    words: set[str] = field(default_factory=set)
    traces: list[dict] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return sum(self.apps.values())

    @property
    def main_app(self) -> str:
        return max(self.apps, key=self.apps.get) if self.apps else ""


def build_episodes(sessions: list[dict], traces: list[dict]) -> list[Episode]:
    """Group a day's sessions and traces into episodes. Pure; no storage."""
    sessions = sorted((s for s in sessions if not is_system_process(s["app_name"])), key=lambda s: s["started_at"])
    traces = sorted(traces, key=lambda t: t["created_at"])

    def traces_during(start: datetime, end: datetime) -> list[dict]:
        return [t for t in traces if start - timedelta(minutes=1) <= _ts(t["created_at"]) <= end + timedelta(minutes=2)]

    episodes: list[Episode] = []
    for s in sessions:
        start, end = _ts(s["started_at"]), _ts(s.get("ended_at") or s.get("effective_end") or s["started_at"])
        seconds = max((end - start).total_seconds(), 0.0)
        title = s.get("window_title") or ""
        if title == "[excluded]":
            title = ""
        s_words = words_of(title + " " + " ".join(t["content"][:400] for t in traces_during(start, end)))
        cur = episodes[-1] if episodes else None
        new = (
            cur is None
            or (start - cur.end).total_seconds() > GAP_SECONDS
            or (cur.end - cur.start).total_seconds() > MAX_EPISODE_SECONDS
            # A long session in an app not yet part of this episode, on unrelated words.
            or (seconds >= MIN_SPLIT_SECONDS and s["app_name"] not in cur.apps
                and cur.seconds >= MIN_SPLIT_SECONDS and jaccard(cur.words, s_words) < TOPIC_SPLIT)
        )
        if new:
            cur = Episode(start=start, end=end)
            episodes.append(cur)
        cur.end = max(cur.end, end)
        cur.apps[s["app_name"]] = cur.apps.get(s["app_name"], 0.0) + seconds
        if title and title not in cur.titles:
            cur.titles.append(title)
        cur.words |= s_words

    # Attach traces to the episode they fall in, or the nearest one within ten minutes.
    for t in traces:
        when = _ts(t["created_at"])
        best, best_gap = None, timedelta(minutes=10)
        for e in episodes:
            if e.start - timedelta(minutes=1) <= when <= e.end + timedelta(minutes=2):
                best, best_gap = e, timedelta(0)
                break
            gap = min(abs(when - e.start), abs(when - e.end))
            if gap <= best_gap:
                best, best_gap = e, gap
        if best is None:
            best = Episode(start=when, end=when, apps={t.get("app_name") or "Notes": 0.0})
            episodes.append(best)
        best.traces.append(t)
        if t.get("window_title") and t["window_title"] not in best.titles:
            best.titles.append(t["window_title"])

    episodes.sort(key=lambda e: e.start)
    return [e for e in episodes if e.traces or e.seconds >= MIN_EPISODE_SECONDS]


# --- writing summaries ------------------------------------------------------

EPISODE_PROMPT = (
    "You summarise one stretch of the user's work from their own captured memories. Use ONLY the "
    "numbered sources. Reply in exactly this format:\n"
    "TITLE: <a short title of at most eight words>\n"
    "SUMMARY: <one to three sentences about what the user was doing or reading, addressed to them as "
    "\"you\", each ending with the source numbers it comes from, like [1] or [2][3]>\n"
    "Do not mention times or durations. Do not invent details."
)

DAY_PROMPT = (
    "You write a short summary of the user's day from the numbered episodes below. Use ONLY them. "
    "Write two to four sentences about the main things the user worked on or read, addressed to them as "
    "\"you\" (\"You reviewed...\"), each ending with the episode numbers it comes from, like [1] or [2][4]. "
    "Do not mention times or durations. Do not invent details."
)


def _complete(llm, system: str, user: str, max_tokens: int = 220) -> str:
    import recall
    with recall._llm_lock:
        out = llm.create_chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            stream=False, temperature=0.1, top_p=0.9, max_tokens=max_tokens)
    return out["choices"][0]["message"]["content"].strip()


def _fallback_title(e: Episode) -> str:
    title = e.titles[0] if e.titles else ""
    title = re.split(r" [-|·—] ", title)[0].strip() if title else ""
    return f"{e.main_app}: {title}"[:80] if title else (e.main_app or "Activity")


def summarise_episode(e: Episode, llm, tz) -> tuple[str, str, list[dict]]:
    """Returns (title, summary, sources) where sources are the cited traces."""
    import recall

    if not e.traces:
        apps = ", ".join(f"{a} ({recall.format_duration(s)})" for a, s in sorted(e.apps.items(), key=lambda kv: -kv[1])[:3])
        return _fallback_title(e), f"Time in {apps}.", []
    # One source per page, the fullest capture, longest first.
    picked = recall.build_sources(sorted(e.traces, key=lambda t: -len(t["content"])), " ".join(e.titles))[:EPISODE_SOURCES]
    for s in picked:
        s.snippet = s.snippet[:EPISODE_SOURCE_CHARS]
    text = _complete(llm, EPISODE_PROMPT, f"Sources:\n\n{recall.source_block(picked, tz)}")
    m_title = re.search(r"TITLE:\s*(.+)", text)
    m_sum = re.search(r"SUMMARY:\s*(.+)", text, re.S)
    title = m_title.group(1).strip().strip('"')[:80] if m_title else ""
    summary_raw = m_sum.group(1).strip() if m_sum else text
    summary, _dropped, cited = recall.check_citations(summary_raw, [s.snippet for s in picked])
    if not title or len(title.split()) > 12:
        title = _fallback_title(e)
    if not summary:
        summary = f"Captured {len(e.traces)} memor{'y' if len(e.traces) == 1 else 'ies'} in {e.main_app}."
        cited = []
    sources = [{"n": s.n, "trace_id": s.id, "app_name": s.app_name, "window_title": s.window_title,
                "url": s.url, "created_at": s.created_at} for s in picked]
    return title, summary, sources


def summarise_day(episodes: list[dict], llm, tz) -> str:
    import recall

    if not episodes:
        return ""
    if len(episodes) == 1:
        return _CITATION.sub("[1]", episodes[0]["summary"]) if episodes[0]["summary"] else ""
    def plain(text: str) -> str:
        return _CITATION.sub("", text).strip()

    block = "\n\n".join(
        f"[{i}] {e['title']} ({datetime.fromisoformat(e['started_at']).astimezone(tz).strftime('%H:%M')})\n{plain(e['summary'])}"
        for i, e in enumerate(episodes, 1))
    text = _complete(llm, DAY_PROMPT, f"Episodes:\n\n{block}", max_tokens=260)
    summary, _dropped, _cited = recall.check_citations(text, [f"{e['title']} {e['summary']}" for e in episodes])
    return summary


# --- running it ----------------------------------------------------------------

def day_bounds(day: date, tz) -> tuple[str, str]:
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    return start.astimezone(timezone.utc).isoformat(), (start + timedelta(days=1)).astimezone(timezone.utc).isoformat()


def consolidate_day(day: date, llm, embed, tz, force: bool = False) -> dict | None:
    """Build and store episodes and the summary for one local day."""
    key = day.isoformat()
    if not force and db.day_exists(key):
        return None
    since, until = day_bounds(day, tz)
    sessions = db.sessions_between(since, until)
    traces = db.traces_between(since, until, limit=10_000)
    built = build_episodes(sessions, traces)

    episodes = []
    for e in built:
        title, summary, sources = summarise_episode(e, llm, tz)
        episodes.append({
            "id": str(uuid.uuid4()), "title": title, "summary": summary,
            "started_at": e.start.astimezone(timezone.utc).isoformat(),
            "ended_at": e.end.astimezone(timezone.utc).isoformat(),
            "apps": [{"app_name": a, "seconds": round(s)} for a, s in sorted(e.apps.items(), key=lambda kv: -kv[1]) if s >= 1],
            "focused_seconds": round(e.seconds), "sources": sources,
            "trace_ids": [t["id"] for t in e.traces],
        })
    totals: dict[str, float] = {}
    for e in episodes:
        for a in e["apps"]:
            totals[a["app_name"]] = totals.get(a["app_name"], 0) + a["seconds"]
    stats = {"focused_seconds": round(sum(totals.values())),
             "top_apps": [{"app_name": a, "seconds": s} for a, s in sorted(totals.items(), key=lambda kv: -kv[1])[:5]],
             "episodes": len(episodes), "traces": len(traces)}
    day_summary = summarise_day(episodes, llm, tz)
    db.save_consolidated_day(key, episodes, day_summary, stats,
                             [embed(e["title"] + ". " + _CITATION.sub("", e["summary"])) for e in episodes])

    # Open loops found in the day's memories.
    import open_loops
    open_loops.detect_and_store(traces, llm)
    return {"day": key, "episodes": episodes, "summary": day_summary, "stats": stats}


def pending_days(tz, today: date | None = None, limit: int = 14) -> list[date]:
    """Past local days that have activity or memories but no consolidation yet."""
    # The user's day ends at 4 AM, so just after midnight yesterday is not finished yet.
    from timeparse import logical_today
    today = today or logical_today(datetime.now(tz))
    earliest = db.earliest_activity_or_trace()
    if not earliest:
        return []
    first = datetime.fromisoformat(earliest).astimezone(tz).date()
    out, d = [], max(first, today - timedelta(days=60))
    while d < today and len(out) < limit:
        if not db.day_exists(d.isoformat()):
            since, until = day_bounds(d, tz)
            if db.has_activity_or_traces(since, until):
                out.append(d)
        d += timedelta(days=1)
    return out


def consolidate_pending(llm, embed, tz, today: date | None = None) -> list[str]:
    done = []
    for d in pending_days(tz, today):
        if consolidate_day(d, llm, embed, tz):
            done.append(d.isoformat())
    if done:
        store.set_setting("last_consolidation", json.dumps({"at": store.now_iso(), "days": done}))
    return done
