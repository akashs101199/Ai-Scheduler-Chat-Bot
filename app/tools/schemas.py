# Stubs we'll fill in later for tool-calling
from pydantic import BaseModel, Field
from typing import List, Optional

class Participant(BaseModel):
    name: Optional[str] = None
    email: str

class GetAvailabilityInput(BaseModel):
    participants: List[Participant]
    window_start: str
    window_end: str
    duration_minutes: int
    organizer_tz: str
    constraints: Optional[dict] = None

class SuggestTimesInput(BaseModel):
    availability_blocks: list
    duration_minutes: int
    organizer_tz: str
    preferences: Optional[dict] = None

class CreateEventInput(BaseModel):
    title: str
    start_time: str
    end_time: str
    attendees: List[Participant]
    location: Optional[str] = None
    conferencing: Optional[str] = Field(default="google_meet")
    description: Optional[str] = None
    organizer_tz: str

class RescheduleEventInput(BaseModel):
    event_id: str
    new_start_time: str
    new_end_time: str

class CancelEventInput(BaseModel):
    event_id: str
