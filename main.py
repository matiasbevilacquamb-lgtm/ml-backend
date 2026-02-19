from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import os
import requests

app = FastAPI()

BASE = "https://api.mercadolibre.com"

def ml_headers():
    headers = {
        "User-Agent": "Mozilla/5.0 (Render) ml-backend/1.0",
        "Accept": "application/json",
    }
    token = os.getenv("ML_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

ML_OAUTH_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"


@app.get("/ml/callback")
def ml_callback(code: str = Query(..., description="Authorization code from Mercado Libre")):
    """
    Mercado Libre redirects here with ?code=...
    We exchange that code for access_token + refresh_token.
    """
    client_id = os.getenv("ML_CLIENT_ID")
    client_secret = os.getenv("ML_CLIENT_SECRET")
    redirect_uri = os.getenv("ML_REDIRECT_URI")  # must match exactly what you used in the auth URL

    if not client_id or not client_secret or not redirect_uri:
        return JSONResponse(
            status_code=500,
            content={
                "error": "missing_env_vars",
                "message": "Set ML_CLIENT_ID, ML_CLIENT_SECRET and ML_REDIRECT_URI in Render Environment Variables",
            },
        )

    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }

    r = requests.post(ML_OAUTH_TOKEN_URL, data=data, timeout=20)

    # We return Mercado Libre response as-is (useful to see refresh_token)
    try:
        payload = r.json()
    except Exception:
        payload = {"raw": r.text}

    return JSONResponse(status_code=r.status_code, content=payload)

@app.get("/sites/MLA")
def get_site():
    r = requests.get(f"{BASE}/sites/MLA", timeout=20, headers=ml_headers())
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return JSONResponse(status_code=r.status_code, content=data)

@app.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = 20):
    params = {"q": q, "limit": limit}
    r = requests.get(f"{BASE}/sites/MLA/search", params=params, timeout=20, headers=ml_headers())
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return JSONResponse(status_code=r.status_code, content=data)
