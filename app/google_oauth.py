import os, json
from fastapi import APIRouter, HTTPException, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from dotenv import load_dotenv
from fastapi.responses import RedirectResponse 

load_dotenv()

router = APIRouter(prefix="/auth/google", tags=["google-auth"])

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

TOKENS_DIR = "tokens"
os.makedirs(TOKENS_DIR, exist_ok=True)

STATE_FILE = os.path.join(TOKENS_DIR, "state.json")
if not os.path.exists(STATE_FILE):
    with open(STATE_FILE, "w") as f:
        json.dump({}, f)

def state_store_get() -> dict:
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}

def state_store_set(data: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)

def token_path(user_id: str) -> str:
    return os.path.join(TOKENS_DIR, f"{user_id}.json")

def load_creds(user_id: str) -> Credentials | None:
    p = token_path(user_id)
    if not os.path.exists(p): return None
    data = json.load(open(p))
    return Credentials.from_authorized_user_info(data, SCOPES)

def save_creds(user_id: str, creds: Credentials):
    with open(token_path(user_id), "w") as f:
        f.write(creds.to_json())

def build_flow() -> Flow:
    if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI:
        raise HTTPException(status_code=500, detail="Google OAuth env vars missing. Check .env.")
    return Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID,
                "project_id": "local",
                # Use v2 auth endpoint so prompt=consent is valid
                "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_secret": CLIENT_SECRET,
                "redirect_uris": [REDIRECT_URI]
            }
        },
        scopes=SCOPES
    )

@router.get("/start")
def start(user_id: str):
    flow = build_flow()
    flow.redirect_uri = REDIRECT_URI
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    store = state_store_get()
    store[state] = {"user_id": user_id}
    state_store_set(store)
    return {"auth_url": auth_url, "state": state}

@router.get("/callback")
def callback(request: Request, state: str | None = None, code: str | None = None):
    # print("CALLBACK QUERY:", dict(request.query_params))  # uncomment to debug errors
    if not state:
        raise HTTPException(status_code=400, detail="Missing state")
    store = state_store_get()
    entry = store.get(state)
    if not entry or "user_id" not in entry:
        raise HTTPException(status_code=400, detail="Unknown or expired state.")
    user_id = entry["user_id"]

    flow = build_flow()
    flow.redirect_uri = REDIRECT_URI
    if not code:
        # Surface Google error message if present
        q = dict(request.query_params)
        raise HTTPException(status_code=400, detail=f"OAuth error: {q.get('error')} {q.get('error_description')}")
    flow.fetch_token(code=code)
    creds = flow.credentials
    save_creds(user_id, creds)

    # cleanup
    store.pop(state, None)
    state_store_set(store)

    return {"ok": True, "message": f"Google connected for {user_id}"}

@router.get("/start/redirect")
def start_redirect(user_id: str):
    data = start(user_id)  # re-use the existing start() to build the URL/state
    return RedirectResponse(url=data["auth_url"])