"""Phase 6: episodes, day summaries, forgetting, Keep and open loops."""

from datetime import date, datetime, timedelta, timezone

import pytest

from evaluation import recall_fixture as fx


def s(app, start, minutes, title=""):
    st = start.astimezone(timezone.utc)
    return {"app_name": app, "window_title": title, "started_at": st.isoformat(),
            "ended_at": (st + timedelta(minutes=minutes)).isoformat()}


def t(tid, when, app, text, title=""):
    return {"id": tid, "created_at": when.astimezone(timezone.utc).isoformat(), "app_name": app,
            "window_title": title, "url": "", "content": text, "source": "screen_ocr"}


# --- grouping rules ---------------------------------------------------------

def test_long_gaps_split_episodes():
    from consolidation import build_episodes
    eps = build_episodes([s("Pages", fx.at(26, 9), 30), s("Pages", fx.at(26, 10), 30)], [])
    assert len(eps) == 2  # a 30-minute gap


def test_short_gaps_and_related_work_merge():
    from consolidation import build_episodes
    sessions = [s("Visual Studio Code", fx.at(26, 9), 40, "recall.py"), s("Google Chrome", fx.at(26, 9, 42), 8, "fusion paper"),
                s("Visual Studio Code", fx.at(26, 9, 51), 30, "recall.py")]
    eps = build_episodes(sessions, [])
    assert len(eps) == 1 and eps[0].main_app == "Visual Studio Code"


def test_a_clear_change_of_topic_and_app_starts_a_new_episode():
    from consolidation import build_episodes
    sessions = [s("Visual Studio Code", fx.at(26, 9), 40, "timeparse.py engram parser"),
                s("Mail", fx.at(26, 9, 41), 25, "Club workshop volunteers")]
    traces = [t("a", fx.at(26, 9, 10), "Visual Studio Code", "def parse_period yesterday timedelta", "timeparse.py"),
              t("b", fx.at(26, 9, 50), "Mail", "mock interview workshop wednesday volunteers", "Club workshop")]
    eps = build_episodes(sessions, traces)
    assert [e.main_app for e in eps] == ["Visual Studio Code", "Mail"]
    assert [x["id"] for x in eps[0].traces] == ["a"] and [x["id"] for x in eps[1].traces] == ["b"]


def test_very_long_blocks_are_split_and_tiny_noise_dropped():
    from consolidation import MAX_EPISODE_SECONDS, build_episodes
    sessions = [s("Xcode", fx.at(26, 8) + timedelta(minutes=50 * i), 50) for i in range(6)]
    eps = build_episodes(sessions + [s("Finder", fx.at(26, 20), 1)], [])
    assert len(eps) >= 2
    assert all((e.end - e.start).total_seconds() <= MAX_EPISODE_SECONDS + 3600 for e in eps)
    assert all(e.main_app != "Finder" for e in eps)


def test_system_dialogs_do_not_form_episodes():
    from consolidation import build_episodes
    assert build_episodes([s("UserNotificationCenter", fx.at(26, 10), 24)], []) == []


# --- consolidating the fixture ---------------------------------------------------

@pytest.fixture
def consolidated(fresh_store):
    import consolidation
    from fake_models import FakeLlama
    from vector_store import embed_text

    fx.load(embed_text)
    llm = FakeLlama()
    done = consolidation.consolidate_pending(llm, embed_text, fx.TZ, today=fx.NOW.date())
    return done, llm, embed_text


def test_pending_days_are_consolidated_once(consolidated):
    import consolidation
    import db

    done, llm, embed = consolidated
    assert done == ["2026-11-26", "2026-11-27"]  # today is not finished
    assert consolidation.consolidate_pending(llm, embed, fx.TZ, today=fx.NOW.date()) == []
    first = db.get_day("2026-11-26")
    assert first["episodes"] and first["summary"]
    assert first["stats"]["focused_seconds"] == 240 * 60


def test_reconsolidating_a_day_replaces_it(consolidated):
    import consolidation
    import db

    _, llm, embed = consolidated
    before = db.get_day("2026-11-26")
    consolidation.consolidate_day(date(2026, 11, 26), llm, embed, fx.TZ, force=True)
    after = db.get_day("2026-11-26")
    assert len(after["episodes"]) == len(before["episodes"])
    assert {e["id"] for e in after["episodes"]}.isdisjoint({e["id"] for e in before["episodes"]})


def test_episode_citations_point_to_real_traces(consolidated):
    import re

    import db

    for day in ("2026-11-26", "2026-11-27"):
        for e in db.get_day(day)["episodes"]:
            cited = {int(n) for n in re.findall(r"\[(\d+)\]", e["summary"])}
            ns = {src["n"] for src in e["sources"]}
            assert cited <= ns, (e["title"], e["summary"])
            trace_ids = {tid for tid, *_ in fx.TRACES}
            assert all(src["trace_id"] in trace_ids for src in e["sources"])


def test_day_summary_cites_its_episodes(consolidated):
    import re

    import db

    day = db.get_day("2026-11-27")
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", day["summary"])}
    assert cited and cited <= set(range(1, len(day["episodes"]) + 1))


def test_recall_answers_a_day_from_its_summary(consolidated):
    import recall

    _, llm, embed = consolidated
    events = list(recall.recall("What did I work on on Thursday?", llm, embed, tz=fx.TZ, now=fx.NOW))
    done = events[-1]
    assert done["route"] == "summary" and done["sources"][0]["kind"] == "episode"
    assert done["answer"].startswith("You were active for 4 hours")


def test_recall_offers_episodes_for_content_questions(consolidated):
    import recall

    _, llm, embed = consolidated
    meta = list(recall.recall("What happened in the meeting with Dr. Lee?", llm, embed, tz=fx.TZ, now=fx.NOW))[0]
    assert any(src["kind"] == "episode" for src in meta["sources"])


# --- forgetting --------------------------------------------------------------------

def test_forgetting_is_off_by_default_and_previews_counts(consolidated):
    import forgetting

    assert forgetting.get_days() == 0
    assert forgetting.run()["faded"] == 0
    later = fx.NOW + timedelta(days=10)
    assert forgetting.preview(7, later)["would_fade"] == 11  # the two consolidated days
    assert forgetting.preview(30, later)["would_fade"] == 0


def test_forgetting_respects_pins_recall_and_keeps_episodes(consolidated):
    import db
    import forgetting

    import store

    db.set_pinned("t03", True)
    recalled_at = (fx.NOW + timedelta(days=9)).astimezone(timezone.utc).isoformat()
    conn = store.connect()
    with conn:  # recalled a day before the run below, so it is fresh
        conn.execute("UPDATE traces SET last_recalled_at = ? WHERE id = 't06'", (recalled_at,))
    forgetting.set_days(7)
    result = forgetting.run(now=fx.NOW + timedelta(days=10))
    remaining = {m["id"] for m in db.get_all_memories()}
    assert "t03" in remaining                    # kept
    assert "t06" in remaining                    # recalled recently
    assert "t04" not in remaining and result["faded"] >= 8
    day = db.get_day("2026-11-26")
    assert day["summary"] and day["episodes"]     # summaries stay
    faded = [src for e in day["episodes"] for src in e["sources"] if src["faded"]]
    assert faded                                  # ...and say which sources faded
    assert any(e["outcome"] == "faded" for e in db.get_capture_log())


def test_unconsolidated_days_never_fade(fresh_store):
    import db
    import forgetting
    from vector_store import embed_text

    fx.load(embed_text)  # nothing consolidated
    forgetting.set_days(7)
    assert forgetting.run(now=fx.NOW + timedelta(days=30))["faded"] == 0
    assert len(db.get_all_memories()) == len(fx.TRACES)


# --- open loops -----------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("TODO: drop stopwords before building the FTS5 query", True),
    ("Remind me to email Dr. Lee the figures.", True),
    ("We still need three volunteers. Please reply by Monday if you can help.", True),
    ("I need to rerun EEGNet on the Siena recordings.", True),
    ("Reciprocal rank fusion combines the rankings of several systems.", False),
    ("The weather is lovely today and the coffee is good.", False),
    ("Final-year CS student who'd rather ship something than build another to-do app.", False),
])
def test_open_loop_candidates(text, expected):
    import open_loops
    assert bool(open_loops.candidates(text)) == expected


def test_open_loops_are_found_classified_and_not_taken_from_web_pages(consolidated):
    import db

    texts = [l["text"] for l in db.get_open_loops()]
    assert any("Please reply by Monday" in x for x in texts)      # Mail
    assert any("TODO" in x for x in texts)                         # code comment
    assert not any("Cormack" in x or "booking" in x.lower() for x in texts)  # browser pages skipped


def test_open_loop_status_changes(consolidated):
    import db

    loop = db.get_open_loops()[0]
    assert db.set_open_loop_status(loop["id"], "done")
    assert loop["id"] not in {l["id"] for l in db.get_open_loops()}
    assert loop["id"] in {l["id"] for l in db.get_open_loops("done")}
