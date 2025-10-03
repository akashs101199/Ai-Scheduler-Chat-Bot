from typing import List, Dict, Any
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from app.google_oauth import load_creds


def service_for(user_id: str):
    """
    Build an authenticated Google Calendar service for the given user_id.
    Requires that OAuth tokens exist (tokens/<user_id>.json) from the /auth/google flow.
    """
    creds: Credentials | None = load_creds(user_id)
    if not creds:
        raise ValueError("Google not connected for this user_id")
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return build("calendar", "v3", credentials=creds)


def freebusy(user_id: str, time_min: str, time_max: str, calendar_id: str = "primary") -> List[Dict[str, str]]:
    """
    Return busy blocks for the user's calendar between time_min and time_max (ISO8601).
    """
    svc = service_for(user_id)
    body = {"timeMin": time_min, "timeMax": time_max, "items": [{"id": calendar_id}]}
    fb = svc.freebusy().query(body=body).execute()
    return fb["calendars"][calendar_id].get("busy", [])


def create_event(
    user_id: str,
    title: str,
    start: str,
    end: str,
    attendees: List[str],
    tz: str,
    conferencing: str = "google_meet"
) -> Dict[str, Any]:
    """
    Create a calendar event with optional Google Meet conferencing.
    Returns dict with event_id, hangoutLink (join link), htmlLink (calendar UI link).
    """
    svc = service_for(user_id)

    event: Dict[str, Any] = {
        "summary": title,
        "start": {"dateTime": start, "timeZone": tz},
        "end":   {"dateTime": end,   "timeZone": tz},
        "attendees": [{"email": e} for e in attendees],
    }

    conf_ver = 0
    if conferencing == "google_meet":
        # Ensure Meet is created and extractable
        event["conferenceData"] = {
            "createRequest": {
                "requestId": f"req-{abs(hash((title, start, end))) % 1_000_000}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"}
            }
        }
        conf_ver = 1

    created = svc.events().insert(
        calendarId="primary",
        body=event,
        conferenceDataVersion=conf_ver,
        sendUpdates="all"
    ).execute()

    # Prefer conferenceData.entryPoints[...].uri; fall back to hangoutLink
    join_link = None
    cd = created.get("conferenceData")
    if cd:
        for ep in (cd.get("entryPoints") or []):
            uri = ep.get("uri")
            if uri:
                join_link = uri
                break
    if not join_link:
        join_link = created.get("hangoutLink")

    return {
        "event_id": created["id"],
        "hangoutLink": join_link,
        "htmlLink": created.get("htmlLink"),
    }
