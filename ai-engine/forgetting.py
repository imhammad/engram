"""Forgetting by design (ADR 0014).

Raw traces fade after a chosen number of days unless they were pinned (Keep)
or recently used in a Recall answer. Episodes and day summaries stay; their
links to faded traces remain, marked faded. Only traces from days that have
been consolidated can fade, so nothing disappears before it has been
summarised. The setting starts at Never; turning it on needs a preview.
"""

import json
from datetime import datetime, timedelta, timezone

import db
import store

CHOICES = {0: "Never", 30: "Gentle", 14: "Balanced", 7: "Brisk"}
VACUUM_AFTER_DELETES = 200
VACUUM_EVERY_DAYS = 7


def get_days() -> int:
    value = store.get_setting("forgetting_days")
    return int(value) if value else 0


def set_days(days: int) -> None:
    store.set_setting("forgetting_days", str(days))


def cutoff(days: int, now: datetime | None = None) -> str:
    return ((now or datetime.now(timezone.utc)) - timedelta(days=days)).astimezone(timezone.utc).isoformat()


def preview(days: int, now: datetime | None = None) -> dict:
    """How many traces would fade at this setting, right now."""
    if days <= 0:
        return {"days": days, "would_fade": 0, "kept_by_pin": 0, "kept_by_recall": 0}
    c = cutoff(days, now)
    return {"days": days, **db.fade_counts(c)}


def run(now: datetime | None = None) -> dict:
    """Fade what the current setting allows. Returns what happened."""
    days = get_days()
    if days <= 0:
        return {"days": 0, "faded": 0}
    c = cutoff(days, now)
    ids = db.fade_candidates(c)
    for trace_id in ids:
        db.delete_memory(trace_id)
    db.mark_episode_sources_faded(ids)
    if ids:
        db.log_capture("forgetting", "faded", "Engram", "", f"{len(ids)} memories older than {days} days faded")
    vacuumed = _maybe_vacuum(len(ids), now)
    return {"days": days, "faded": len(ids), "vacuumed": vacuumed}


def _maybe_vacuum(deleted: int, now: datetime | None) -> bool:
    now = now or datetime.now(timezone.utc)
    state = json.loads(store.get_setting("forgetting_state") or "{}")
    pending = state.get("deleted_since_vacuum", 0) + deleted
    last = datetime.fromisoformat(state["last_vacuum"]) if state.get("last_vacuum") else None
    do_it = pending > 0 and (pending >= VACUUM_AFTER_DELETES or not last or now - last > timedelta(days=VACUUM_EVERY_DAYS))
    if do_it:
        conn = store.connect()
        conn.execute("VACUUM")
        state = {"deleted_since_vacuum": 0, "last_vacuum": now.isoformat()}
    else:
        state["deleted_since_vacuum"] = pending
    store.set_setting("forgetting_state", json.dumps(state))
    return do_it
