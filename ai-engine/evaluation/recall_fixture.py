"""A synthetic three-day memory and the questions to evaluate Recall with.

Thursday 26 to Saturday 28 November 2026, Malaysia time (UTC+8): coding,
reading, a meeting note, mail, chat, shopping and travel. "Now" is Saturday
18:00. Each question has its type, the words a correct answer must contain
(any one of each group) and the ids of the memories that support it.
Unanswerable questions have no gold sources and must be declined.
"""

from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 28, 18, 0, tzinfo=TZ)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


# id, local time, app, window title, url, text
TRACES = [
    ("t01", at(26, 9, 40), "Visual Studio Code", "recall.py — engram", "",
     "def hybrid_search(query, embedding, limit=5):\n    keyword = keyword_ranking(query, 20)\n"
     "    vector = vector_ranking(embedding, 20)\n    return reciprocal_rank_fusion(keyword, vector)[:limit]\n"
     "# TODO: drop stopwords before building the FTS5 query so questions do not match on 'the'"),
    ("t02", at(26, 10, 30), "Google Chrome", "Reciprocal rank fusion outperforms Condorcet - paper", "https://plg.uwaterloo.ca/rrf.pdf",
     "Reciprocal rank fusion combines the rankings of several retrieval systems by summing 1 / (k + rank) for each "
     "document. The constant k = 60 was found to work well across collections. RRF needs no score calibration "
     "and outperformed Condorcet fusion and individual rank learning methods in the TREC experiments by Cormack and Clarke."),
    ("t03", at(26, 14, 5), "Notes", "Meeting with Dr. Lee", "",
     "Meeting with Dr. Lee about cross-dataset seizure detection.\nAfter Euclidean alignment the sensitivity on Siena rose "
     "from 61 percent to 78 percent and false alarms fell by a third.\nAction items: rerun EEGNet on the Siena recordings with "
     "the aligned features and prepare figures.\nNext meeting is Thursday at 3pm in room 204."),
    ("t04", at(26, 16, 20), "Google Chrome", "Electroencephalography - Wikipedia", "https://en.wikipedia.org/wiki/Electroencephalography",
     "Electroencephalography (EEG) is a method to record an electrogram of the spontaneous electrical activity of the brain. "
     "The biosignals detected by EEG represent the postsynaptic potentials of pyramidal neurons in the neocortex. "
     "EEG is commonly used to diagnose epilepsy, which causes abnormalities in EEG readings."),
    ("t05", at(26, 20, 15), "Google Chrome", "Booking.com: Hotel Maya Kuala Lumpur", "https://www.booking.com/hotel/my/maya",
     "Your booking is confirmed. Hotel Maya Kuala Lumpur, check-in Friday 12 December 2026, check-out Sunday 14 December 2026. "
     "Deluxe room, breakfast included, free cancellation until 10 December."),
    ("t06", at(27, 9, 15), "Google Chrome", "Paolo Mignone | LinkedIn", "https://www.linkedin.com/in/paolo-mignone",
     "Paolo Mignone. Associate Professor and Senior ML and Predictive AI Scientist. Research-driven proofs of concept, "
     "benchmarking, model evaluation and research reports. Based in Italy. 500+ connections."),
    ("t07", at(27, 11, 0), "Visual Studio Code", "ax.rs — engram", "",
     "pub fn is_secure(role: &str, subrole: &str) -> bool {\n    role == \"AXSecureTextField\" || subrole == \"AXSecureTextField\"\n}\n"
     "// Password fields are never read. The accessibility walk stops after 6000 elements or 600 ms."),
    ("t08", at(27, 13, 30), "Google Chrome", "SQLCipher API documentation", "https://www.zetetic.net/sqlcipher/sqlcipher-api/",
     "SQLCipher encrypts the whole database file with 256-bit AES. Set the key with PRAGMA key. A raw key can be given as a "
     "hex blob literal, PRAGMA key = \"x'2DD29CA8...'\", which skips the key derivation function entirely."),
    ("t09", at(27, 15, 45), "Mail", "Re: CS club workshop", "",
     "Hi all, the CS club mock interview workshop is on Wednesday at 5pm in the main lecture hall. We still need three "
     "volunteers to act as interviewers. Please reply by Monday if you can help. Thanks, Farah"),
    ("t10", at(27, 17, 10), "Google Chrome", "Use Stage Manager on Mac - Apple Support", "https://support.apple.com/guide/mac-help/stage-manager",
     "Stage Manager keeps the window you are working in front and centre, and arranges your other apps in a strip on the "
     "left side of the screen so you can switch to them with a click."),
    ("t11", at(27, 21, 30), "Notes", "Grocery list", "",
     "Grocery list for the weekend: oat milk, coffee beans, basmati rice, spinach, eggs and dark chocolate."),
    ("t12", at(28, 9, 30), "Google Chrome", "Qwen/Qwen3-4B-Instruct-2507 · Hugging Face", "https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507",
     "Qwen3-4B-Instruct-2507 is a 4 billion parameter instruction-tuned model released under the Apache 2.0 license. "
     "It supports a native context length of 262,144 tokens and improves instruction following, reasoning and coding."),
    ("t13", at(28, 11, 0), "Visual Studio Code", "timeparse.py — engram", "",
     "def parse_period(question, now):\n    # 'yesterday' means the whole previous local day\n    # 'last week' is the previous calendar week, Monday to Monday\n"
     "    if 'yesterday' in question: return whole_day(today - timedelta(days=1))"),
    ("t14", at(28, 13, 0), "Google Chrome", "lofi hip hop radio - YouTube", "https://www.youtube.com/watch?v=jfKfPfyJRdk",
     "lofi hip hop radio beats to relax and study to. Live. Subscribe. Like. Share."),
    ("t15", at(28, 14, 20), "Slack", "#research - Lab", "",
     "Aisha: good news, our access to the CHB-MIT extension dataset was approved this morning. I will share the download "
     "link by Monday. Please do not redistribute the files outside the lab."),
    ("t16", at(28, 16, 45), "Google Chrome", "AirAsia booking confirmation", "https://www.airasia.com/booking",
     "Flight AK 6125 from Alor Setar to Kuala Lumpur on Friday 12 December 2026, departing 08:30 and arriving 09:25. "
     "One passenger, 20 kg checked baggage."),
]

# app, local start, minutes
SESSIONS = [
    ("Visual Studio Code", at(26, 9, 0), 75), ("Google Chrome", at(26, 10, 15), 50), ("Slack", at(26, 11, 5), 10),
    ("Notes", at(26, 14, 0), 40), ("Google Chrome", at(26, 16, 0), 45), ("Google Chrome", at(26, 20, 0), 20),
    ("Google Chrome", at(27, 9, 0), 30), ("Visual Studio Code", at(27, 10, 30), 120), ("Google Chrome", at(27, 13, 15), 35),
    ("Mail", at(27, 15, 30), 15), ("Google Chrome", at(27, 17, 0), 25), ("Notes", at(27, 21, 25), 10),
    ("Google Chrome", at(28, 9, 20), 40), ("Visual Studio Code", at(28, 10, 30), 90), ("Google Chrome", at(28, 12, 50), 30),
    ("Slack", at(28, 14, 15), 20), ("Google Chrome", at(28, 16, 30), 25),
]

# type, question, required keyword groups (each group: any one matches), gold source ids
QUESTIONS = [
    # Activity: answered from sessions; numbers are exact.
    ("activity", "How long was I in Chrome today?", [["1 hour 35 minutes"]], []),
    ("activity", "Which apps did I use yesterday?", [["Visual Studio Code"], ["Google Chrome"]], []),
    ("activity", "How much time did I spend in VS Code on Thursday?", [["1 hour 15 minutes"]], []),
    ("activity", "When did I last use Slack today?", [["14:15"]], []),
    ("activity", "How long was I active yesterday?", [["3 hours 55 minutes"]], []),
    ("activity", "When did I first use VS Code today?", [["10:30"]], []),
    ("activity", "How long was I in Mail on Thursday?", [["didn't use"]], []),
    ("activity", "Which apps did I use the most on Thursday?", [["Google Chrome (1 hour 55 minutes)"]], []),
    # Content: retrieval and a grounded answer.
    ("content", "What was that EEG article about?", [["electrical", "brain"]], ["t04"]),
    ("content", "Who is Paolo Mignone?", [["professor", "machine learning", "ML", "scientist"]], ["t06"]),
    ("content", "What was the sensitivity on Siena after alignment?", [["78"]], ["t03"]),
    ("content", "Where is my next meeting with Dr. Lee?", [["204"]], ["t03"]),
    ("content", "What do I need to rerun for Dr. Lee?", [["EEGNet"]], ["t03"]),
    ("content", "When is the CS club mock interview workshop?", [["Wednesday"]], ["t09"]),
    ("content", "What's on my grocery list?", [["oat milk", "coffee", "rice", "spinach", "eggs", "chocolate"]], ["t11"]),
    ("content", "What license is Qwen3-4B released under?", [["Apache"]], ["t12"]),
    ("content", "What value of k does reciprocal rank fusion use?", [["60"]], ["t02"]),
    ("content", "Which dates is my Kuala Lumpur hotel booked for?", [["12"], ["14"]], ["t05"]),
    ("content", "What time does my flight to Kuala Lumpur leave?", [["08:30", "8:30"]], ["t16"]),
    ("content", "What did Aisha say about the dataset?", [["approved"]], ["t15"]),
    ("content", "How do you give SQLCipher a raw key?", [["x'", "hex", "blob", "PRAGMA"]], ["t08"]),
    ("content", "What did I read about Stage Manager?", [["strip", "left", "side"]], ["t10"]),
    # Period summaries: activity totals plus a cited summary.
    ("summary", "What did I work on yesterday?", [["Paolo", "accessibility", "SQLCipher", "club", "workshop", "Stage Manager", "secure"]], ["t06", "t07", "t08", "t09", "t10", "t11"]),
    ("summary", "What did I do on Thursday?", [["seizure", "EEG", "fusion", "hotel", "Dr. Lee", "hybrid"]], ["t01", "t02", "t03", "t04", "t05"]),
    ("summary", "Give me a recap of today", [["Qwen", "dataset", "flight", "timeparse", "parse", "Aisha"]], ["t12", "t13", "t14", "t15", "t16"]),
    # Unanswerable: nothing in memory supports an answer.
    ("unanswerable", "What is my bank account number?", [], []),
    ("unanswerable", "What did the doctor say about my blood test?", [], []),
    ("unanswerable", "What was the score of the football match last night?", [], []),
    ("unanswerable", "Where did I park my car?", [], []),
    ("unanswerable", "What is Aisha's phone number?", [], []),
]


def load(embed) -> None:
    """Insert the fixture into the configured store."""
    import db

    for tid, when, app, title, url, text in TRACES:
        db.insert_trace(text, embed(text), source="screen_ocr", app_name=app, window_title=title, url=url,
                        created_at=when.astimezone(timezone.utc).isoformat(), trace_id=tid, text_source="accessibility")
    for app, start, minutes in SESSIONS:
        s = start.astimezone(timezone.utc)
        db.insert_session(app, "", s.isoformat(), (s + timedelta(minutes=minutes)).isoformat(), "switch")
