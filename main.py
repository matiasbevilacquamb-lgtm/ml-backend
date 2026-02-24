from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import os
import requests
import statistics
import time
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

# ===== TOKEN MANAGEMENT =====
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"

_token_cache = {
    "access_token": None,
    "expires_at": 0,
}
def refresh_access_token():
    client_id = os.getenv("ML_CLIENT_ID")
    client_secret = os.getenv("ML_CLIENT_SECRET")
    refresh_token = os.getenv("ML_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError("Missing ML credentials in environment variables")

    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }

    r = requests.post(TOKEN_URL, data=payload, timeout=20)
    data = r.json()

    if r.status_code != 200:
        raise RuntimeError(f"Error refreshing token: {data}")

    access_token = data["access_token"]
    expires_in = int(data.get("expires_in", 21600))
    new_refresh = data.get("refresh_token")

    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = int(time.time()) + expires_in - 60

    if new_refresh and new_refresh != refresh_token:
        print("⚠️ NEW REFRESH TOKEN (update in Render env):", new_refresh)

    return access_token


def get_access_token():
    if (
        _token_cache["access_token"]
        and time.time() < _token_cache["expires_at"]
    ):
        return _token_cache["access_token"]

    return refresh_access_token()
# ===== ENDPOINTS =====
@app.get("/ml/test-auth")
def ml_test_auth():
    token = get_access_token()

    r = requests.get(
        "https://api.mercadolibre.com/users/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20
    )

    return {
        "status_code": r.status_code,
        "response": r.json()
    }
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
import statistics

@app.get("/market/analysis")
def market_analysis(q: str, limit: int = 50):

    r = requests.get(
        f"{BASE}/sites/MLA/search",
        params={"q": q, "limit": limit},
        timeout=20
    )

    data = r.json()
    items = data.get("results", [])

    # Filtrar solo nuevos y con ventas reales
    filtered = [
        i for i in items
        if i.get("sold_quantity", 0) > 1
        and i.get("condition") == "new"
    ]

    if len(filtered) < 3:
        return {"error": "Not enough real sales data"}

    prices = [i["price"] for i in filtered]
    sold_quantities = [i["sold_quantity"] for i in filtered]

    avg_price = sum(prices) / len(prices)
    std_dev = statistics.stdev(prices) if len(prices) > 1 else 0

    # Eliminar outliers
    cleaned = [
        i for i in filtered
        if std_dev == 0 or abs(i["price"] - avg_price) <= 2 * std_dev
    ]

    prices_clean = [i["price"] for i in cleaned]
    sold_clean = [i["sold_quantity"] for i in cleaned]

    weighted_avg_clean = sum(p * s for p, s in zip(prices_clean, sold_clean)) / sum(sold_clean)

    top_5 = sorted(cleaned, key=lambda x: x["sold_quantity"], reverse=True)[:5]

    top_5_clean = [
        {
            "title": i["title"],
            "price": i["price"],
            "sold_quantity": i["sold_quantity"],
            "link": i["permalink"]
        }
        for i in top_5
    ]

    return {
        "query": q,
        "items_analyzed": len(cleaned),
        "weighted_average_price": round(weighted_avg_clean, 2),
        "min_price": min(prices_clean),
        "max_price": max(prices_clean),
        "top_5_best_sellers": top_5_clean
    }
