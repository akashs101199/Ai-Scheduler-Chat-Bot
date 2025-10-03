from typing import Dict, Any, List
from datetime import datetime, timezone, timedelta
from dateutil import parser as dtparse
from zoneinfo import ZoneInfo

from app.google_calendar import freebusy, create_event as g_create


def _normalize_attendees(attendees_raw) -> List[str]:
    """
    Accepts:
      - "a@x.com"
      - "a@x.com, b@y.com" (or semicolon-separated)
      - ["a@x.com", "b@y.com"]
      - [{"email":"a@x.com"}, ...]
      - {"email":"a@x.com"}
    Returns: list[str] of emails.
    """
    emails: List[str] = []

    def add_email(s: str):
        s = (s or "").strip()
        if s and "@" in s:
            emails.append(s)

    if isinstance(attendees_raw, str):
        parts = attendees_raw.replace(";", ",").split(",")
        for p in parts:
            add_email(p)

    elif isinstance(attendees_raw, dict):
        add_email(attendees_raw.get("email", ""))

    elif isinstance(attendees_raw, list):
        for item in attendees_raw:
            if isinstance(item, str):
                add_email(item)
            elif isinstance(item, dict):
                add_email(item.get("email", ""))

    # de-dupe while preserving order
    seen = set()
    result = []
    for e in emails:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result


async def get_availability(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check busy slots for the organizer and participants.
    """
    user_id = params.get("organizer_user_id", "demo")
    tz_name = params.get("organizer_tz", "America/New_York")
    tz = ZoneInfo(tz_name)

    window_start = params["window_start"]
    window_end = params["window_end"]

    try:
        ws = dtparse.isoparse(window_start)
        we = dtparse.isoparse(window_end)
    except Exception:
        raise ValueError("window_start/window_end must be ISO8601")

    if ws.tzinfo is None:
        ws = ws.replace(tzinfo=tz)
    if we.tzinfo is None:
        we = we.replace(tzinfo=tz)

    now_utc = datetime.now(timezone.utc)
    while we <= now_utc:
        ws += timedelta(days=7)
        we += timedelta(days=7)

    window_start = ws.isoformat()
    window_end = we.isoformat()

    participants = params.get("participants", [])
    if isinstance(participants, str):
        participants = [{"email": p.strip()} for p in participants.replace(";", ",").split(",") if p.strip()]

    busy = freebusy(user_id, window_start, window_end)
    return {
        "window_start": window_start,
        "window_end": window_end,
        "busy": busy,
        "participants": participants,
        "duration_minutes": params.get("duration_minutes", 30),
    }


async def create_event(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a Google Calendar event.
    Ensures times are timezone-aware and ALWAYS in the future.
    Rolls forward past suggestions by full weeks until valid.
    """
    user_id = params.get("organizer_user_id", "demo")

    attendee_emails = _normalize_attendees(params.get("attendees", []))
    fallback_title = f"Meeting with {attendee_emails[0]}" if attendee_emails else "Meeting"
    title = (params.get("title") or fallback_title).strip()

    start = params.get("start_time")
    end = params.get("end_time")
    if not start or not end:
        raise ValueError("create_event requires start_time and end_time (ISO strings).")

    tz_name = params.get("organizer_tz", "America/New_York")
    tz = ZoneInfo(tz_name)

    try:
        start_dt = dtparse.isoparse(start)
        end_dt = dtparse.isoparse(end)
    except Exception:
        raise ValueError("start_time/end_time must be ISO8601 (e.g., 2025-10-07T15:00:00-04:00).")

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tz)
    else:
        start_dt = start_dt.astimezone(tz)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=tz)
    else:
        end_dt = end_dt.astimezone(tz)

    # If the suggested slot is in the past, roll forward to the next valid week
    now_local = datetime.now(tz)
    if end_dt <= now_local:
        delta_days = (now_local - end_dt).days
        weeks = (delta_days // 7) + 1
        jump = timedelta(days=7 * weeks)
        start_dt += jump
        end_dt += jump

    if end_dt <= start_dt:
        raise ValueError("end_time must be after start_time.")

    conf = params.get("conferencing", "google_meet")

    created = g_create(
        user_id=user_id,
        title=title,
        start=start_dt.isoformat(),
        end=end_dt.isoformat(),
        attendees=attendee_emails,
        tz=tz_name,
        conferencing=conf,
    )

    return {
        "event_id": created["event_id"],
        "join_link": created.get("hangoutLink"),
        "calendar_link": created.get("htmlLink"),
        "title": title,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "attendees": attendee_emails,
    }
