from .google_tools import get_availability, create_event   # real Google-backed
from .mock_tools import suggest_times                      # keep mock ranker

TOOL_REGISTRY = {
    "get_availability": get_availability,
    "suggest_times": suggest_times,
    "create_event": create_event,
}
