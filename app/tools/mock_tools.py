from __future__ import annotations
from datetime import datetime, timedelta
from dateutil import parser as dtparse
from zoneinfo import ZoneInfo
from typing import List, Dict, Any

def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()

def clamp_to_window(start: datetime, end: datetime, wstart: datetime, wend: datetime):
    s = max(start, wstart); e = min(end, wend)
    return (s, e) if e > s else None

async def suggest_times(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Given busy blocks + window + constraints, propose up to 3 candidate slots.
    Ensures all times are timezone-aware using organizer_tz (default ET).
    """
    avail = params["availability_blocks"]

    tz_name = params.get("organizer_tz") or "America/New_York"
    tz = ZoneInfo(tz_name)

    # Parse window and coerce tz if missing
    wstart = dtparse.isoparse(avail["window_start"])
    wend = dtparse.isoparse(avail["window_end"])
    if wstart.tzinfo is None:
        wstart = wstart.replace(tzinfo=tz)
    if wend.tzinfo is None:
        wend = wend.replace(tzinfo=tz)

    duration = timedelta(minutes=params.get("duration_minutes", 30))
    prefs = params.get("preferences") or {}
    hours = (prefs.get("hours") or {"start":"13:00","end":"17:00"})  # afternoon default window
    hstart_h, hstart_m = map(int, hours["start"].split(":"))
    hend_h, hend_m = map(int, hours["end"].split(":"))
    days = set((prefs.get("days") or []))  # e.g. {"Tue","Wed"}

    # Build daily free blocks within work hours
    free_blocks: List[Dict[str, str]] = []
    day_cursor = wstart.replace(hour=hstart_h, minute=hstart_m, second=0, microsecond=0)
    while day_cursor < wend:
        day_start = day_cursor
        day_end = day_cursor.replace(hour=hend_h, minute=hend_m)
        if day_end > day_start:
            maybe = clamp_to_window(day_start, day_end, wstart, wend)
            if maybe:
                d0, d1 = maybe
                if not days or d0.strftime("%a") in days:
                    free_blocks.append({"start": iso(d0), "end": iso(d1)})
        # advance one local day (keep tz)
        day_cursor = (day_cursor + timedelta(days=1)).replace(hour=hstart_h, minute=hstart_m)

    # Normalize busy blocks with tz
    busy = []
    for b in avail.get("busy", []):
        bs = dtparse.isoparse(b["start"])
        be = dtparse.isoparse(b["end"])
        if bs.tzinfo is None: bs = bs.replace(tzinfo=tz)
        if be.tzinfo is None: be = be.replace(tzinfo=tz)
        busy.append((bs, be))

    # Subtract busy from free
    refined: List[Dict[str, str]] = []
    for block in free_blocks:
        s = dtparse.isoparse(block["start"]); e = dtparse.isoparse(block["end"])
        segments = [(s, e)]
        for (bs, be) in busy:
            nxt = []
            for (xs, xe) in segments:
                if xe <= bs or be <= xs:
                    nxt.append((xs, xe)); continue
                if xs < bs: nxt.append((xs, bs))
                if be < xe: nxt.append((be, xe))
            segments = nxt
        for (xs, xe) in segments:
            if (xe - xs) >= duration:
                refined.append({"start": iso(xs), "end": iso(xe)})

    # Propose up to 3 candidates with tz-aware times
    proposals = []
    for block in refined:
        start_dt = dtparse.isoparse(block["start"])
        end_dt = start_dt + duration
        if end_dt <= dtparse.isoparse(block["end"]):
            proposals.append({"start": iso(start_dt), "end": iso(end_dt), "score": 0.8})
        if len(proposals) >= 3:
            break

    return {
        "candidates": proposals,
        "window_start": iso(wstart),
        "window_end": iso(wend),
        "duration_minutes": params.get("duration_minutes", 30),
        "organizer_tz": tz_name,
    }
