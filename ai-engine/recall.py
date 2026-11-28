"""Recall: answer a question from the user's own memories, with sources.

The pipeline (ADR 0012):

1. Find the time period the question is about (timeparse, local time).
2. Route the question:
   - activity ("how long was I in Chrome today?", "which apps yesterday?",
     "when did I last use VS Code?") is answered straight from the
     activity_sessions table. The numbers never pass through the model.
   - summary ("what did I work on yesterday?") combines the period's
     activity totals, stated deterministically, with a short cited summary
     of that period's memories written by the model.
   - content (everything else) uses hybrid retrieval with the period and
     app as filters, then a grounded answer from the model.
3. Grounding: sources are numbered in the prompt and every sentence must
   cite at least one. Afterwards citations are checked against the real
   sources and uncited sentences are dropped. If nothing relevant was found,
   or nothing cited survives, the answer says so instead of guessing.

Answers are produced as a stream of events so the interface can show the
text as it is written.
"""

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator

import db
from search import relevant_search
from timeparse import Period, parse_period

NOT_FOUND = "I couldn't find that in your memories."
MAX_SOURCES = 5
SOURCE_CHARS = 1000          # per source, after picking its most relevant part
CONTEXT_CHARS = 4500         # all sources together; keeps prompt processing near two seconds
SUMMARY_SOURCES = 8

_llm_lock = threading.Lock()  # llama.cpp contexts are not thread-safe

APP_ALIASES = {
    "chrome": "Google Chrome", "google chrome": "Google Chrome", "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code", "code editor": "Visual Studio Code", "terminal": "Terminal",
    "safari": "Safari", "slack": "Slack", "mail": "Mail", "notes": "Notes", "claude": "Claude",
}

ACTIVITY_PATTERNS = [
    r"\bhow (?:long|much time)\b", r"\b(?:which|what) apps?\b", r"\bmost time\b",
    r"\btime (?:spent|did i spend)\b", r"\bscreen ?time\b", r"\bwhen did i (?:last |first )?(?:use|open|start|switch to|work in)\b",
    r"\bhow many (?:hours|minutes)\b", r"\bwhere did i spend\b",
]
SUMMARY_PATTERNS = [
    r"\bwhat (?:did|have) i (?:work(?:ed)? on|do|done|been doing|been working on)\b", r"\bsummar(?:y|ise|ize)\b",
    r"\brecap\b", r"\bwhat was i (?:doing|working on|up to)\b", r"\bwhat have i been up to\b", r"\bmy day\b",
]


@dataclass
class Source:
    n: int
    id: str
    app_name: str
    window_title: str
    url: str
    created_at: str
    snippet: str
    kind: str = "memory"   # memory | activity | episode

    def card(self) -> dict:
        return {"n": self.n, "id": self.id, "app_name": self.app_name, "window_title": self.window_title,
                "url": self.url, "created_at": self.created_at, "snippet": self.snippet[:280], "kind": self.kind}


@dataclass
class Plan:
    route: str                          # activity | summary | content
    period: Period | None
    app: str | None
    sources: list[Source] = field(default_factory=list)


# --- understanding the question ---------------------------------------------

# Words that carry no subject in a question to Engram ("can I ask you a question?").
_SMALL_TALK_WORDS = {
    "hi", "hello", "hey", "thanks", "thank", "ok", "okay", "cool", "great", "good", "morning", "evening",
    "can", "could", "may", "ask", "question", "questions", "help", "engram", "you", "your", "yourself",
    "work", "works", "something", "anything", "please", "yes", "no", "sure", "how", "are", "doing", "who",
    "what", "is", "am", "do", "does", "the", "a", "an", "i", "me", "my", "to", "of", "it", "this", "that",
    "use", "able", "there", "be", "will", "would", "tell", "about", "know", "remember", "for", "with",
}
SMALL_TALK_REPLY = (
    "Of course. Ask me about anything you saw, read or did on this Mac, for example \"What was that "
    "article about?\", \"What did I work on yesterday?\" or \"How long was I in Chrome today?\". I answer only "
    "from your own memories, and I'll tell you when something isn't in them."
)


def is_small_talk(question: str) -> bool:
    """Greetings and questions about Engram itself, with no subject to look up."""
    words = re.findall(r"[a-z']+", question.lower())
    return bool(words) and all(w.strip("'") in _SMALL_TALK_WORDS for w in words)


def classify(question: str) -> str:
    q = question.lower()
    if is_small_talk(question):
        return "chat"
    if any(re.search(p, q) for p in ACTIVITY_PATTERNS):
        return "activity"
    if any(re.search(p, q) for p in SUMMARY_PATTERNS):
        return "summary"
    return "content"


def find_app(question: str, known: list[str]) -> str | None:
    q = question.lower()
    for name in sorted(known, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name.lower()) + r"\b", q):
            return name
    for alias, name in APP_ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", q) and (name in known or not known):
            return name
    return None


def format_duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s} seconds" if s != 1 else "1 second"
    m = s // 60
    if m < 60:
        return f"{m} minute{'s' if m != 1 else ''}"
    h, m = divmod(m, 60)
    return f"{h} hour{'s' if h != 1 else ''}" + (f" {m} minute{'s' if m != 1 else ''}" if m else "")


def when(period: Period) -> str:
    """Period label as it reads in a sentence: "today", "on Tuesday 24 November"."""
    first = period.label.split(" ")[0].lower()
    return f"on {period.label}" if first in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday") else period.label


def _local(iso: str, tz) -> datetime:
    return datetime.fromisoformat(iso).astimezone(tz)


def _clock(iso: str, tz) -> str:
    return _local(iso, tz).strftime("%H:%M")


# --- activity answers (no model) ---------------------------------------------

def _overlap_seconds(session: dict, since: str, until: str) -> float:
    start = max(session["started_at"], since)
    end = min(session["effective_end"], until)
    return max((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 0.0)


def answer_activity(question: str, period: Period, app: str | None, tz) -> dict:
    since, until = period.as_utc_iso()
    from exclusions import is_system_process

    sessions = [s for s in db.sessions_between(since, until) if not is_system_process(s["app_name"])]
    totals: dict[str, float] = {}
    for s in sessions:
        totals[s["app_name"]] = totals.get(s["app_name"], 0.0) + _overlap_seconds(s, since, until)
    ranked = sorted(((a, t) for a, t in totals.items() if t >= 1), key=lambda kv: kv[1], reverse=True)
    breakdown = [{"app_name": a, "seconds": round(t)} for a, t in ranked[:8]]
    q = question.lower()

    if not ranked:
        return {"answer": f"I have no activity recorded {when(period)}.", "breakdown": []}

    if app:
        app_sessions = [s for s in sessions if s["app_name"] == app]
        if not app_sessions:
            return {"answer": f"You didn't use {app} {when(period)}, as far as Engram recorded.", "breakdown": breakdown}
        if re.search(r"\bwhen did i\b", q):
            first, last = app_sessions[0], app_sessions[-1]
            if re.search(r"\blast\b", q):
                text = f"The last time you used {app} {when(period)} was at {_clock(last['started_at'], tz)}."
            elif re.search(r"\bfirst\b", q):
                text = f"You first used {app} {when(period)} at {_clock(first['started_at'], tz)}."
            else:
                text = (f"You used {app} {when(period)} from {_clock(first['started_at'], tz)}, "
                        f"most recently at {_clock(last['started_at'], tz)}.")
            return {"answer": text, "breakdown": breakdown}
        total = totals.get(app, 0.0)
        share = total / sum(totals.values()) if totals else 0
        return {"answer": (f"You spent {format_duration(total)} in {app} {when(period)}, "
                           f"{share:.0%} of your active time, across {len(app_sessions)} session"
                           f"{'s' if len(app_sessions) != 1 else ''}."),
                "breakdown": breakdown}

    total = sum(t for _, t in ranked)
    top = ", ".join(f"{a} ({format_duration(t)})" for a, t in ranked[:3])
    return {"answer": f"You were active for {format_duration(total)} {when(period)}. Most of it went to {top}.",
            "breakdown": breakdown}


# --- retrieval and grounding ---------------------------------------------------

def reflow(text: str) -> str:
    """Rejoin text that Accessibility split around links and formatting.

    A web page's text arrives as many short pieces ("is a method to record
    an", "electrogram", "of the spontaneous..."). Lines that don't end a
    sentence are joined to the next, so the model reads prose, not a list."""
    out: list[str] = []
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            continue
        if (out and len(out[-1]) < 400 and not re.search(r"[.!?:;]$", out[-1])
                and (len(out[-1]) < 80 or line[:1].islower() or line[:1] in ",.;:)]")):
            sep = "" if line[:1] in ",.;:)]" or out[-1].endswith(("(", "[")) else " "
            out[-1] = out[-1] + sep + line
        else:
            out.append(line)
    return "\n".join(out)


def best_excerpt(text: str, question: str, limit: int = SOURCE_CHARS) -> str:
    """The part of a long trace that best matches the question's words."""
    text = reflow(text)
    if len(text) <= limit:
        return text
    # Start with the document's opening paragraph (what it is about), then the
    # part that best matches the question.
    lead = next((l for l in text.splitlines() if len(l.split()) >= 12), "")[:350] if limit >= 600 else ""
    if lead:
        rest = best_excerpt(text.replace(lead, "", 1), question, limit - len(lead) - 5) if limit - len(lead) > 200 else ""
        return f"{lead}\n...\n{rest}" if rest else lead
    words = {w for w in re.findall(r"\w+", question.lower()) if len(w) > 2}
    lines = [l for l in text.splitlines() if l.strip()]
    best_start, best_score = 0, -1
    for i in range(len(lines)):
        window, chars, j = [], 0, i
        while j < len(lines) and (not window or chars + len(lines[j]) <= limit):
            window.append(lines[j])
            chars += len(lines[j]) + 1
            j += 1
        score = sum(len(words & set(re.findall(r"\w+", l.lower()))) for l in window)
        if score > best_score:
            best_start, best_score = i, score
    out, chars = [], 0
    for line in lines[best_start:]:
        if out and chars + len(line) > limit:
            break
        out.append(line)
        chars += len(line) + 1
    return "\n".join(out)


def _page(m: dict):
    return (m.get("app_name"), m.get("url") or m.get("window_title")) if (m.get("url") or m.get("window_title")) else m["id"]


def build_sources(memories: list[dict], question: str) -> list[Source]:
    # Several captures of the same page add nothing but length: keep one per
    # page, in the rank of its best-ranked capture, using the fullest text
    # (an Accessibility capture of the whole page beats an earlier OCR one).
    order, fullest = [], {}
    for m in memories:
        page = _page(m)
        if page not in fullest:
            order.append(page)
            fullest[page] = m
        elif len(m["content"]) > len(fullest[page]["content"]):
            fullest[page] = m
    sources, used = [], 0
    for m in (fullest[p] for p in order):
        excerpt = best_excerpt(m["content"], question)
        if used + len(excerpt) > CONTEXT_CHARS and sources:
            break
        used += len(excerpt)
        sources.append(Source(len(sources) + 1, m["id"], m.get("app_name", ""), m.get("window_title", ""),
                              m.get("url", ""), m["created_at"], excerpt))
    return sources


def source_block(sources: list[Source], tz) -> str:
    parts = []
    for s in sources:
        when = _local(s.created_at, tz).strftime("%a %d %b %H:%M")
        where = " · ".join(x for x in (s.app_name, s.window_title, s.url) if x)
        parts.append(f"[{s.n}] ({when}; {where})\n{s.snippet}")
    return "\n\n".join(parts)


SYSTEM_PROMPT = (
    "You are Engram, a private memory assistant. Answer the user's question using ONLY the numbered "
    "sources from their own memories, speaking to them as \"you\". Rules: every sentence must end with the number of the source it "
    "comes from, like [1] or [2][3]. Do not use outside knowledge. Do not invent details. Keep it to "
    "one to four short sentences. If the sources do not contain the answer, reply with exactly: "
    + NOT_FOUND
)

SUMMARY_PROMPT = (
    "You are Engram, a private memory assistant. Summarise what the user worked on, using ONLY the "
    "numbered sources from their own memories. Write two to four short sentences about the main "
    "topics and tasks. Every sentence must end with the source numbers it comes from, like [1] or "
    "[2][4]. Do not mention times or durations. Do not invent details."
)


_CITE = re.compile(r"\[(\d+)\]")
_ABBREVIATIONS = ("Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "St.", "e.g.", "i.e.", "vs.", "etc.", "approx.", "No.")
_STOP = re.compile(r"[.!?]")


def split_sentences(text: str) -> list[str]:
    """Split an answer into sentences, keeping trailing citations ("... brain.[1]")
    with their sentence and not splitting on "Dr.", "2.0" or "...".
    """
    protected = text
    for abbr in _ABBREVIATIONS:
        protected = protected.replace(abbr, abbr.replace(".", "\x00"))
    protected = re.sub(r"(?<=\d)\.(?=\d)", "\x00", protected)   # 2.0, 08.30
    protected = protected.replace("...", "\x00\x00\x00")
    pieces = re.findall(r"[^.!?\n]+(?:[.!?]+(?:\s*\[\d+\])*)?|\s*\[\d+\]", protected)
    return [p.replace("\x00", ".").strip() for p in pieces if p.strip()]


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4}


def supported(sentence: str, source_text: str, threshold: float = 0.6) -> bool:
    """Most of the sentence's content words appear in the source."""
    words = _content_words(_CITE.sub("", sentence))
    return bool(words) and len(words & _content_words(source_text)) / len(words) >= threshold


def check_citations(answer: str, sources: list[str] | int) -> tuple[str, int, list[int]]:
    """Keep only sentences that cite a real source. Returns (clean text,
    sentences dropped, source numbers cited).

    A sentence without a citation is kept only when the next cited sentence's
    source supports it (most of its words are in that source): writers often
    cite once at the end of a short run of sentences. Anything else uncited
    is dropped. Citations to sources that do not exist are removed.
    """
    texts = sources if isinstance(sources, list) else [""] * sources
    n_sources = len(texts)
    if "couldn't find" in answer.lower() or "could not find" in answer.lower():
        return "", 0, []
    kept, dropped, cited = [], 0, []
    waiting: list[str] = []   # uncited sentences that a following citation may cover
    for sentence in split_sentences(answer):
        valid = [n for n in (int(x) for x in _CITE.findall(sentence)) if 1 <= n <= n_sources]
        body = " ".join(_CITE.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_sources else "", sentence).split())
        if not _CITE.sub("", body).strip(" ."):
            # A bare citation after the full stop belongs to the previous sentence(s).
            if valid and waiting:
                kept.extend(waiting[:-1] + [waiting[-1] + " " + "".join(f"[{n}]" for n in valid)])
                waiting = []
                cited += valid
            elif valid and kept:
                kept[-1] += " " + "".join(f"[{n}]" for n in valid)
                cited += valid
            continue
        if not valid:
            waiting.append(body)
            continue
        for w in waiting:
            if any(supported(w, texts[n - 1]) for n in valid):
                kept.append(w)
            else:
                dropped += 1
        waiting = []
        kept.append(body)
        cited += valid
    dropped += len(waiting)
    return " ".join(kept), dropped, sorted(set(cited))


# --- the pipeline --------------------------------------------------------------

Event = dict


def recall(question: str, llm, embed: Callable[[str], list[float]], tz=None, now: datetime | None = None) -> Iterator[Event]:
    """Answer a question as a stream of events:
    {"type": "meta", ...}, then {"type": "token", "text": ...} while the
    model writes, then {"type": "done", "answer": ..., "sources": [...], ...}."""
    tz = tz or datetime.now().astimezone().tzinfo
    now = now or datetime.now(tz)
    period = parse_period(question, now)
    route = classify(question)
    known = db.known_app_names()
    app = find_app(question, known)

    if route == "chat":
        yield {"type": "meta", "route": route, "period": None, "sources": []}
        yield {"type": "done", "route": route, "answer": SMALL_TALK_REPLY, "sources": [], "dropped_sentences": 0}
        return

    if route == "activity":
        result = answer_activity(question, period or Period(now.replace(hour=0, minute=0, second=0, microsecond=0), now, "today"), app, tz)
        yield {"type": "meta", "route": route, "period": (period.label if period else "today"), "sources": []}
        yield {"type": "done", "route": route, "answer": result["answer"], "breakdown": result["breakdown"],
               "sources": [], "dropped_sentences": 0}
        return

    if route == "summary":
        period = period or Period(now.replace(hour=0, minute=0, second=0, microsecond=0), now, "today")
        day = _whole_day(period)
        stored = db.get_day(day) if day else None
        if stored and stored["summary"]:
            # Already consolidated: answer from the day summary and its episodes.
            activity = answer_activity("which apps", period, None, tz)
            cards = [episode_card(i, e, tz) for i, e in enumerate(stored["episodes"], 1)]
            lead = activity["answer"] if activity["breakdown"] else ""
            cited = {int(n) for n in _CITE.findall(stored["summary"])}
            yield {"type": "meta", "route": route, "period": period.label, "sources": cards, "breakdown": activity["breakdown"]}
            yield {"type": "done", "route": route, "answer": " ".join(x for x in (lead, stored["summary"]) if x),
                   "breakdown": activity["breakdown"], "sources": [c for c in cards if c["n"] in cited] or cards,
                   "dropped_sentences": 0}
            return
        since, until = period.as_utc_iso()
        activity = answer_activity("which apps", period, None, tz)
        memories = _pick_summary_traces(db.traces_between(since, until, limit=200))
        sources = build_sources(memories, question)
        yield {"type": "meta", "route": route, "period": period.label, "sources": [s.card() for s in sources],
               "breakdown": activity["breakdown"]}
        lead = activity["answer"] if activity["breakdown"] else ""
        if not sources:
            final = (lead + " " if lead else "") + f"I have no saved memories {when(period)} to summarise."
            yield {"type": "done", "route": route, "answer": final.strip(), "breakdown": activity["breakdown"],
                   "sources": [], "dropped_sentences": 0}
            return
        if lead:
            yield {"type": "token", "text": lead + " "}
        text = yield from _generate(llm, SUMMARY_PROMPT, sources, f"What did I work on {when(period)}?", tz)
        body, dropped, cited = check_citations(text, [s.snippet for s in sources])
        final = " ".join(x for x in (lead, body) if x) or NOT_FOUND
        db.touch_recalled([s.id for s in sources if s.n in cited])
        yield {"type": "done", "route": route, "answer": final, "breakdown": activity["breakdown"],
               "sources": [s.card() for s in sources if s.n in cited], "dropped_sentences": dropped}
        return

    # Content questions.
    since, until = period.as_utc_iso() if period else (None, None)
    q_embedding = embed(question)
    ids = relevant_search(question, q_embedding, limit=MAX_SOURCES, since=since, until=until, app=app)
    by_id = db.get_memories_by_ids(ids)
    # Consolidated episodes first: they summarise whole stretches of work and
    # survive after their raw traces fade (ADR 0013).
    from search import STOPWORDS
    q_words = {w for w in re.findall(r"[a-z0-9]+", question.lower()) if len(w) >= 4 and w not in STOPWORDS}
    episodes = db.get_episodes_by_ids(db.episode_search(q_words, q_embedding, since, until))
    sources = [Source(i, e["id"], ", ".join(a["app_name"] for a in e["apps"][:2]), e["title"], "", e["started_at"],
                      f"Episode: {e['title']}. {_CITE.sub('', e['summary']).strip()}", kind="episode")
               for i, e in enumerate(episodes.values(), 1)]
    for s in build_sources([by_id[i] for i in ids if i in by_id], question):
        s.n = len(sources) + 1
        sources.append(s)
    # Songs, videos and sites often exist only as window titles in activity:
    # add matching sessions as sources too.
    for item in activity_matches(question, period, tz):
        if len(sources) >= MAX_SOURCES + 2:
            break
        sources.append(Source(len(sources) + 1, item["id"], item["app_name"], item["window_title"], "",
                              item["started_at"], item["snippet"], kind="activity"))
    yield {"type": "meta", "route": route, "period": period.label if period else None,
           "sources": [s.card() for s in sources]}
    if not sources:
        yield {"type": "done", "route": route, "answer": NOT_FOUND, "sources": [], "dropped_sentences": 0}
        return
    text = yield from _generate(llm, SYSTEM_PROMPT, sources, question, tz)
    body, dropped, cited = check_citations(text, [s.snippet for s in sources])
    final = body or NOT_FOUND
    db.touch_recalled([s.id for s in sources if s.n in cited and s.kind == "memory"])
    yield {"type": "done", "route": route, "answer": final,
           "sources": [s.card() for s in sources if s.n in cited], "dropped_sentences": dropped}


# Question words that say nothing about which window was meant.
_ACTIVITY_NOISE = {"listen", "listened", "listening", "watch", "watched", "watching", "visit", "visited",
                   "open", "opened", "song", "songs", "video", "videos", "music", "site", "website", "page",
                   "last", "night", "today", "yesterday", "morning", "evening", "any", "did", "was", "were"}


def activity_matches(question: str, period: Period | None, tz, limit: int = 3) -> list[dict]:
    """Activity sessions whose window title or app name shares words with the
    question, grouped per window, best first. "Did I listen to Higher Love on
    YouTube Music last night?" finds the session titled
    "YouTube Music - Higher Love"."""
    from search import STOPWORDS
    words = {w for w in re.findall(r"[a-z0-9]+", question.lower())
             if len(w) >= 3 and w not in STOPWORDS and w not in _ACTIVITY_NOISE}
    # App names count too ("YouTube Music"), so keep app words from the question.
    app_words = {w for w in re.findall(r"[a-z0-9]+", question.lower()) if len(w) >= 3 and w not in STOPWORDS}
    if not app_words:
        return []
    since, until = period.as_utc_iso() if period else ("0000", "9999")
    grouped: dict[tuple, dict] = {}
    for s in db.sessions_between(since, until):
        title = s["window_title"] or ""
        if title == "[excluded]":
            continue
        hay = set(re.findall(r"[a-z0-9]+", (title + " " + s["app_name"]).lower()))
        score = 2 * len(words & hay) + len(app_words & set(re.findall(r"[a-z0-9]+", s["app_name"].lower())))
        if score == 0:
            continue
        key = (s["app_name"], title)
        g = grouped.setdefault(key, {"score": score, "first": s["started_at"], "seconds": 0.0, "id": "session:" + s["id"]})
        g["seconds"] += s.get("duration_seconds") or 0.0
        g["first"] = min(g["first"], s["started_at"])
    ranked = sorted(grouped.items(), key=lambda kv: (-kv[1]["score"], kv[1]["first"]))[:limit]
    out = []
    for (app, title), g in ranked:
        dur = f" for {format_duration(g['seconds'])}" if g["seconds"] >= 60 else ""
        out.append({"id": g["id"], "app_name": app, "window_title": title, "started_at": g["first"],
                    "snippet": f"Activity: the window \"{title or app}\" in {app} was open at "
                               f"{_local(g['first'], tz).strftime('%a %d %b %H:%M')}{dur}."})
    return out


def _whole_day(period: Period) -> str | None:
    """The local date if the period is exactly one whole day, else None."""
    s, e = period.start, period.end
    if s.hour == s.minute == 0 and (e - s).days == 1 and e.hour == e.minute == 0:
        return s.date().isoformat()
    return None


def episode_card(n: int, e: dict, tz) -> dict:
    start = _local(e["started_at"], tz).strftime("%H:%M")
    end = _local(e["ended_at"], tz).strftime("%H:%M")
    return {"n": n, "id": e["id"], "kind": "episode", "app_name": ", ".join(a["app_name"] for a in e["apps"][:2]),
            "window_title": e["title"], "url": "", "created_at": e["started_at"],
            "snippet": f"{start} to {end}. {_CITE.sub('', e['summary']).strip()}"}


def _pick_summary_traces(traces: list[dict]) -> list[dict]:
    """A spread of the period's memories: the longest from each window, most recent first."""
    best: dict[tuple, dict] = {}
    for t in traces:
        key = (t.get("app_name"), t.get("url") or t.get("window_title"))
        if key not in best or len(t["content"]) > len(best[key]["content"]):
            best[key] = t
    picked = sorted(best.values(), key=lambda t: t["created_at"], reverse=True)
    return picked[:SUMMARY_SOURCES]


def _generate(llm, system: str, sources: list[Source], question: str, tz):
    """Stream the model's answer as token events; returns the full text."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Sources:\n\n{source_block(sources, tz)}\n\nQuestion: {question}"},
    ]
    parts: list[str] = []
    with _llm_lock:
        for chunk in llm.create_chat_completion(messages=messages, stream=True, temperature=0.1,
                                                top_p=0.9, max_tokens=320):
            delta = chunk["choices"][0].get("delta", {}).get("content")
            if delta:
                parts.append(delta)
                yield {"type": "token", "text": delta}
    return "".join(parts).strip()
