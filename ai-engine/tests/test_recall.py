"""Recall: routing, activity answers from SQL, grounded answers with
citations, abstention, streaming and history. Fake models, network blocked."""

import json
from datetime import datetime, timedelta, timezone

import pytest

import recall
from test_api import engine, no_network  # noqa: F401  (fixtures)

EEG = ("Electroencephalography (EEG) is a method to record an electrogram of the spontaneous electrical "
       "activity of the brain. The biosignals detected by EEG represent the postsynaptic potentials of "
       "pyramidal neurons in the neocortex.")
PROFILE = ("Paolo Mignone. Associate Professor and senior machine learning scientist working on "
           "predictive AI, benchmarking and model evaluation research.")


@pytest.fixture
def client(engine):
    return engine[1]


def ask(client, question, stream=False):
    resp = client.post("/recall", json={"question": question, "stream": stream})
    if stream:
        return [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    return resp.json()


def seed(client):
    client.post("/capture/screen", json={"app_name": "Google Chrome", "window_title": "Electroencephalography - Wikipedia",
                                         "url": "https://en.wikipedia.org/wiki/Electroencephalography", "text": EEG})
    client.post("/capture/screen", json={"app_name": "Google Chrome", "window_title": "Paolo Mignone | LinkedIn",
                                         "url": "https://www.linkedin.com/in/paolo", "text": PROFILE})


# --- routing -----------------------------------------------------------------

@pytest.mark.parametrize("q,route", [
    ("How long was I in Chrome today?", "activity"),
    ("which apps did I use yesterday", "activity"),
    ("when did I last use VS Code?", "activity"),
    ("how much time did I spend in Terminal this week", "activity"),
    ("What did I work on yesterday?", "summary"),
    ("give me a recap of this morning", "summary"),
    ("what was I doing last night", "summary"),
    ("What was that EEG article about?", "content"),
    ("who is Paolo Mignone", "content"),
])
def test_routing(q, route):
    assert recall.classify(q) == route


def test_app_names_are_matched_including_aliases():
    known = ["Google Chrome", "Visual Studio Code", "Terminal"]
    assert recall.find_app("time in chrome today", known) == "Google Chrome"
    assert recall.find_app("when did I use VS Code", known) == "Visual Studio Code"
    assert recall.find_app("what about Terminal", known) == "Terminal"
    assert recall.find_app("what was that article", known) is None


# --- grounding -----------------------------------------------------------------

def test_citation_check_keeps_cited_and_drops_the_rest():
    sources = ["EEG records brain activity from the scalp.", "Neurons fire in the neocortex."]
    text = "EEG records brain activity [1]. It was invented on Mars. Neurons fire [2][9]."
    clean, dropped, cited = recall.check_citations(text, sources)
    assert clean == "EEG records brain activity [1]. Neurons fire [2]."
    assert dropped == 1 and cited == [1, 2]


def test_uncited_sentence_is_kept_only_if_the_next_source_supports_it():
    sources = ["Paolo Mignone. Associate Professor and senior ML scientist. Based in Italy."]
    ok = "Paolo Mignone is an Associate Professor and senior ML scientist. He is based in Italy [1]."
    assert recall.check_citations(ok, sources) == (ok, 0, [1])
    invented = "He won a Nobel prize in physics. He is based in Italy [1]."
    assert recall.check_citations(invented, sources) == ("He is based in Italy [1].", 1, [1])


def test_sentence_splitting_handles_abbreviations_versions_and_trailing_citations():
    parts = recall.split_sentences("Meet Dr. Lee about version 2.0 at 08.30.[1] Then rest. [2]")
    assert parts == ["Meet Dr. Lee about version 2.0 at 08.30.[1]", "Then rest. [2]"]


def test_citation_check_recognises_abstention():
    assert recall.check_citations("I couldn't find that in your memories.", 3) == ("", 0, [])


def test_best_excerpt_picks_the_matching_part():
    text = "\n".join([f"filler line number {i} about nothing" for i in range(80)] + ["The seminar is in room 204 on Thursday."])
    assert "room 204" in recall.best_excerpt(text, "where is the seminar room", limit=300)


# --- content answers -------------------------------------------------------------

def test_content_answer_cites_the_right_source(client):
    seed(client)
    result = ask(client, "What was that EEG article about?")
    assert result["route"] == "content"
    assert "[1]" in result["answer"]
    assert result["sources"][0]["url"] == "https://en.wikipedia.org/wiki/Electroencephalography"


def test_unanswerable_question_abstains(client):
    seed(client)
    result = ask(client, "What is my passport number?")
    assert result["answer"] == recall.NOT_FOUND
    assert result["sources"] == []


def test_empty_memory_abstains(client):
    assert ask(client, "what was that article about volcanoes")["answer"] == recall.NOT_FOUND


def test_answers_stream_as_events(client):
    seed(client)
    events = ask(client, "Tell me about the EEG article", stream=True)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "meta" and kinds[-1] == "done" and "token" in kinds
    assert events[0]["sources"]


# --- activity answers --------------------------------------------------------------

def test_activity_answer_comes_from_sessions(client):
    now = datetime.now(timezone.utc)
    t = lambda m: (now - timedelta(minutes=m)).isoformat()  # noqa: E731
    client.post("/activity", json={"app_name": "Google Chrome", "window_title": "Docs", "at": t(50)})
    client.post("/activity", json={"app_name": "Visual Studio Code", "window_title": "main.py", "at": t(20)})
    client.post("/activity/stop", json={"reason": "idle", "ended_at": t(5)})
    result = ask(client, "How long was I in Chrome today?")
    assert result["route"] == "activity"
    assert "30 minutes in Google Chrome" in result["answer"]
    apps = ask(client, "which apps did I use today")
    assert apps["breakdown"][0] == {"app_name": "Google Chrome", "seconds": 1800}
    assert "Visual Studio Code (15 minutes)" in apps["answer"]


def test_activity_with_nothing_recorded(client):
    assert "no activity recorded" in ask(client, "how long was I in Chrome yesterday")["answer"]


# --- summaries ---------------------------------------------------------------------

def test_summary_combines_activity_and_cited_memories(client):
    now = datetime.now(timezone.utc)
    client.post("/activity", json={"app_name": "Google Chrome", "window_title": "EEG", "at": (now - timedelta(minutes=40)).isoformat()})
    seed(client)
    result = ask(client, "What did I work on today?")
    assert result["route"] == "summary"
    assert result["answer"].startswith("You were active for")
    assert "[" in result["answer"] and result["sources"]


# --- history -------------------------------------------------------------------------

def test_history_is_saved_and_cleared(client):
    seed(client)
    ask(client, "What was that EEG article about?")
    history = client.get("/recall/history").json()
    assert history[0]["question"] == "What was that EEG article about?"
    assert client.delete("/recall/history").json()["deleted_count"] == 1
    assert client.get("/recall/history").json() == []


def test_empty_question_is_rejected(client):
    assert client.post("/recall", json={"question": "  "}).status_code == 422


def test_several_captures_of_one_page_become_one_source():
    page = {"app_name": "Google Chrome", "url": "https://en.wikipedia.org/wiki/EEG", "window_title": "EEG", "created_at": "2026-11-27T10:00:00+00:00"}
    memories = [{**page, "id": "a", "content": "EEG first capture"}, {**page, "id": "b", "content": "EEG second capture"},
                {"id": "c", "app_name": "Notes", "url": "", "window_title": "Lee", "content": "Meeting", "created_at": "2026-11-27T11:00:00+00:00"}]
    assert [s.id for s in recall.build_sources(memories, "eeg")] == ["a", "c"]
