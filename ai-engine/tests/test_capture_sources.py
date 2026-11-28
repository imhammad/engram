"""Phase 4: Accessibility text first, OCR fallback, change-aware recapture,
settings, system dialogs and deterministic clean-up."""

import pytest

import cleanup
from test_api import engine, no_network  # noqa: F401  (fixtures: network blocked, fake models)
import text_change
from text_quality import accessibility_noise_reason, noise_reason

ARTICLE = (
    "Cross-dataset seizure detection notes\n"
    "Most seizure detection models fall apart when they are tested on a hospital's data they were not trained on.\n"
    "Domain alignment methods such as Euclidean alignment and CORAL reduce the gap between recordings.\n"
)
NEXT_SECTION = (
    "Results on Siena\n"
    "After alignment, sensitivity rose from 61 to 78 percent while false alarms per hour fell by a third.\n"
    "The largest gain came from patients with focal seizures recorded on the older montage.\n"
)


@pytest.fixture
def client(engine):
    return engine[1]


def capture(client, **body):
    body.setdefault("app_name", "Google Chrome")
    body.setdefault("window_title", "Seizure notes")
    return client.post("/capture/screen", json=body).json()


# --- text source order ------------------------------------------------------

def test_accessibility_text_is_used_first(client, monkeypatch):
    monkeypatch.setenv("ENGRAM_FAKE_OCR_TEXT", "OCR text that should not be used here at all, really not")
    resp = capture(client, text=ARTICLE, url="https://example.org/notes", trigger="dwell")
    assert resp["saved"] is True
    assert resp["memory"]["text_source"] == "accessibility"
    assert resp["memory"]["url"] == "https://example.org/notes"
    assert "Euclidean alignment" in resp["memory"]["content"]
    entry = client.get("/ledger").json()[0]
    assert entry["text_source"] == "accessibility" and entry["url"] == "https://example.org/notes"


def test_falls_back_to_ocr_when_accessibility_text_is_not_useful(client, monkeypatch):
    monkeypatch.setenv("ENGRAM_FAKE_OCR_TEXT", ARTICLE)
    resp = capture(client, text="Home\nMenu\nSign in", trigger="dwell")
    assert resp["saved"] is True and resp["memory"]["text_source"] == "ocr"


def test_falls_back_to_ocr_without_accessibility_text(client, monkeypatch):
    monkeypatch.setenv("ENGRAM_FAKE_OCR_TEXT", ARTICLE)
    resp = capture(client, trigger="dwell")
    assert resp["memory"]["text_source"] == "ocr"


def test_redaction_applies_to_accessibility_text_and_url(client):
    text = ARTICLE + "Send the draft to jane.doe@example.com and use token ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8\n"
    resp = capture(client, text=text, url="https://mail.example.com/?to=jane.doe@example.com")
    content = resp["memory"]["content"]
    assert "jane.doe" not in content and "[email]" in content and "[secret]" in content
    assert "jane.doe" not in resp["memory"]["url"]


def test_name_heavy_page_passes_the_accessibility_gate():
    """A profile page full of names and short labels: fine as real text, not as OCR."""
    page = ("Paolo Mignone\nSenior ML Engineer · Toronto, ON\n500+ connections\nAbout\n"
            "EEG, BCI, PyTorch, CUDA, MLOps\nExperience\nNeuroTech Inc. · 3 yrs")
    assert accessibility_noise_reason(page) is None


# --- change-aware recapture -------------------------------------------------

PAGE = ARTICLE + NEXT_SECTION + (
    "Before training, check every recording for an anomalous montage and inconsistent channel ordering.\n"
    "Byte-identical duplicate channels would silently poison the results if nobody checked for them.\n"
    "Next steps: rerun EEGNet on CHB-MIT and Siena with the aligned features and compare false alarms.\n"
    "Write up the results for the Thursday meeting with Dr. Lee in room 204 and share the figures.\n"
)


def test_scroll_sized_change_counts_cosmetic_change_does_not():
    assert text_change.changed(ARTICLE, NEXT_SECTION)
    # Scrolling half a screen: the top third goes, a new section arrives.
    scrolled = PAGE.split("\n", 3)[3] + "Appendix A lists every recording, its sampling rate and the montage it used.\n" * 1
    scrolled += "Appendix B explains how the false alarm rate was computed per hour of recording.\n"
    scrolled += "Appendix C covers patient consent, anonymisation and the data sharing agreement.\n"
    assert text_change.changed(PAGE, scrolled)
    # A clock, a badge count and a cursor: not a change worth storing.
    cosmetic = PAGE.replace("Cross-dataset", "Cross-dataset (3)") + "Last updated 10:42"
    assert not text_change.changed(PAGE, cosmetic)
    assert text_change.near_duplicate(PAGE, cosmetic)
    assert text_change.changed(None, ARTICLE)


def test_recheck_saves_only_when_the_window_changed(client):
    first = capture(client, text=ARTICLE, url="https://example.org/a", trigger="dwell")
    assert first["saved"]
    same = capture(client, text=ARTICLE + "Last updated 10:42", url="https://example.org/a", trigger="recheck")
    assert same["saved"] is False and same["unchanged"] is True
    scrolled = capture(client, text=NEXT_SECTION, url="https://example.org/a", trigger="recheck")
    assert scrolled["saved"] is True
    ledger = client.get("/ledger").json()
    assert [e["trigger"] for e in ledger] == ["changed", "dwell"]  # unchanged rechecks are not logged


def test_near_duplicates_are_never_stored(client):
    capture(client, text=ARTICLE, trigger="dwell")
    again = capture(client, text=ARTICLE + "\n3 new notifications", trigger="manual")
    assert again["saved"] is False
    assert client.get("/ledger").json()[0]["outcome"] == "duplicate"
    assert len(client.get("/memories").json()) == 1


# --- settings -----------------------------------------------------------------

def test_capture_settings_default_update_and_validation(client):
    assert client.get("/settings/capture").json() == {"dwell_seconds": 30, "recapture_minutes": 2}
    updated = client.put("/settings/capture", json={"dwell_seconds": 15, "recapture_minutes": 0}).json()
    assert updated == {"dwell_seconds": 15, "recapture_minutes": 0}
    assert client.get("/settings/capture").json() == updated
    assert client.put("/settings/capture", json={"dwell_seconds": 7, "recapture_minutes": 2}).status_code == 422
    assert client.put("/settings/capture", json={"dwell_seconds": 30, "recapture_minutes": 3}).status_code == 422


# --- system dialogs -------------------------------------------------------------

def test_system_dialogs_are_ignored(client, engine):
    main, _ = engine
    assert client.post("/activity", json={"app_name": "UserNotificationCenter", "window_title": ""}).json()["ignored"]
    assert client.get("/activity").json() == []
    resp = capture(client, app_name="SecurityAgent", text=ARTICLE)
    assert resp["saved"] is False and client.get("/ledger").json() == []
    # Sessions already stored for a system process (imported data) are left out of Today.
    __import__("db").insert_session("UserNotificationCenter", "", "2026-11-27T10:00:00+00:00", "2026-11-27T10:20:00+00:00", "switch")
    __import__("db").insert_session("Pages", "Doc", "2026-11-27T10:20:00+00:00", "2026-11-27T10:30:00+00:00", "switch")
    apps = client.get("/activity/today", params={"since": "2026-11-27T00:00:00+00:00"}).json()["apps"]
    assert [a["app_name"] for a in apps] == ["Pages"]


def test_exclusions_endpoint_lists_system_processes(client):
    assert "UserNotificationCenter" in client.get("/exclusions").json()["system_processes"]


# --- deterministic clean-up -----------------------------------------------------

def test_cleanup_drops_boilerplate_repeats_and_counters():
    text = "Home\nMy Network\nArticle title\nArticle title\n  Real   sentence here.  \n12\nAccept all cookies"
    assert cleanup.clean_text(text) == "Article title\nReal sentence here."


def test_cleanup_drops_lines_repeated_across_other_windows():
    others = ["Site header\nFirst story", "Site header\nSecond story", "Site header\nThird story"]
    assert cleanup.clean_text("Site header\nFourth story", others) == "Fourth story"
    # Two sightings are not enough to call it chrome.
    assert cleanup.clean_text("Site header\nX", others[:2]) == "Site header\nX"


def test_ocr_gate_is_still_strict():
    assert noise_reason("@ © ® 8 Bie O's AIM & x + +> eaiA 2? BO qq ww ee") is not None


def test_keep_saves_and_pins_and_keeps_an_existing_capture(client):
    first = capture(client, text=ARTICLE, trigger="keep")
    assert first["saved"] is True and first["kept"] is True
    assert client.get(f"/memories/{first['memory']['id']}").json()["pinned"] is True
    other = capture(client, window_title="Other", text=NEXT_SECTION, trigger="dwell")
    again = capture(client, window_title="Other", text=NEXT_SECTION + " 3 new", trigger="keep")
    assert again["kept"] is True and again["memory"]["id"] == other["memory"]["id"]
    assert client.get(f"/memories/{other['memory']['id']}").json()["pinned"] is True
    assert client.get("/ledger").json()[-1]["trigger"] == "keep"
