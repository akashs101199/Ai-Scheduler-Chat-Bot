import os, json
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import Dict, Any

from app.tools import TOOL_REGISTRY
from app.google_oauth import router as google_auth_router

load_dotenv()

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "180"))

SYSTEM_PROMPT = (
    "You are a scheduling assistant that can call tools by returning EXACTLY ONE JSON object.\n"
    "When you want to use a tool, return ONLY:\n"
    "{\"tool\":\"<name>\",\"args\":{...}}\n"
    "No other text, no code fences, no explanations.\n"
    "If you don't need a tool, reply in plain text (NO JSON).\n"
    "Available tools: get_availability, suggest_times, create_event.\n"
    "Typical flow:\n"
    "1) If the user asks to book or check times -> call get_availability.\n"
    "2) After you receive a tool_result for availability -> call suggest_times.\n"
    "3) After user confirms a slot -> call create_event.\n"
    "When calling create_event, include title, start_time, end_time, attendees (emails), organizer_tz, and conferencing. If title is missing, use Meeting with <first attendee>.\n"
    "Dates must resolve to the FUTURE. If a parsed date/time is in the past, move it forward to the next valid occurrence (same weekday/time) before calling create_event.\n"
    
)

FEW_SHOT = []  # optional: add examples later

class ChatIn(BaseModel):
    user_id: str
    message: str

class ChatOut(BaseModel):
    reply: str

app = FastAPI()
app.include_router(google_auth_router)

async def call_llm(messages: list[dict]) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0}
    }
    timeout = httpx.Timeout(OLLAMA_TIMEOUT, read=OLLAMA_TIMEOUT, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
            return (data.get("message") or {}).get("content") or ""
    except httpx.ReadTimeout:
        raise HTTPException(
            status_code=504,
            detail=f"Ollama timed out after {int(OLLAMA_TIMEOUT)}s. "
                   "First request can be slow while the model loads. Try again or increase OLLAMA_TIMEOUT."
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {e}")

def maybe_parse_tool_call(text: str) -> Dict[str, Any] | None:
    text = text.strip()
    if not text.startswith("{"):
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "tool" in obj and "args" in obj:
            return obj
    except json.JSONDecodeError:
        pass
    return None

@app.get("/health")
async def health():
    reachable = False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
            rr = await client.get(f"{OLLAMA_HOST}/api/tags")
            rr.raise_for_status()
            reachable = True
    except httpx.HTTPError:
        pass
    return {"ok": True, "model": OLLAMA_MODEL, "ollama_reachable": reachable, "timeout_sec": OLLAMA_TIMEOUT}

@app.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn):
    # Ask the model
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *FEW_SHOT,
        {"role": "user", "content": body.message},
    ]
    first = await call_llm(messages)

    # Check for a tool call
    tool_call = maybe_parse_tool_call(first)
    if not tool_call:
        return ChatOut(reply=first)

    name = tool_call["tool"]
    args = tool_call.get("args", {})
    # Ensure organizer user_id is passed down to tools that need it
    args.setdefault("organizer_user_id", body.user_id)

    func = TOOL_REGISTRY.get(name)
    if not func:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {name}")

    # Execute the tool
    try:
        result = await func(args)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tool {name} error: {e}")

    # Send tool result back to the model and get final reply
    messages.extend([
        {"role": "assistant", "content": json.dumps({"tool_result": {"name": name, "result": result}})}
    ])
    final = await call_llm(messages)
    return ChatOut(reply=final or "(no response)")
