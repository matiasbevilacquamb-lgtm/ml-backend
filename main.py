from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import os
import time
import requests

app = FastAPI()

BASE = "https://api.mercadolibre.com"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"

# ===== Helpers =====
def ml_headers():
    # Para endpoints públicos NO hace falta Authorization.
    # Igual mandamos User-Agent/Accept para evitar respuestas raras.
    return {
        "User-Agent": "Mozilla/5.0 (Render) ml-backend/1.0",
        "Accept": "application/json",
    }

# ===== TOKEN MANAGEMENT (OAuth) =====
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
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"Non-JSON response from ML token endpoint: {r.text}")

    if r.status_code != 200:
        raise RuntimeError(f"Error refreshing token: {data}")

    access_token = data["access_token"]
    expires_in = int(data.get("expires_in", 21600))
    new_refresh = data.get("refresh_token")

    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = int(time.time()) + expires_in - 60

    # ML a veces rota el refresh token
    if new_refresh and new_refresh != refresh_token:
        print("⚠️ NEW REFRESH TOKEN (update in Render env):", new_refresh)

    return access_token

def get_access_token():
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]
    return refresh_access_token()

# ===== ENDPOINTS =====

@app.get("/ml/test-auth")
def ml_test_auth():
    token = get_access_token()
    r = requests.get(
        f"{BASE}/users/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20
    )
    try:
        payload = r.json()
    except Exception:
        payload = {"raw": r.text}

    return {"status_code": r.status_code, "response": payload}

@app.get("/ml/callback")
def ml_callback(code: str = Query(..., description="Authorization code from Mercado Libre")):
    """
    Mercado Libre redirects here with ?code=...
    We exchange that code for access_token + refresh_token.
    """
    client_id = os.getenv("ML_CLIENT_ID")
    client_secret = os.getenv("ML_CLIENT_SECRET")
    redirect_uri = os.getenv("ML_REDIRECT_URI")

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

    r = requests.post(TOKEN_URL, data=data, timeout=20)

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
    r = requests.get(
        f"{BASE}/sites/MLA/search",
        params={"q": q, "limit": limit},
        timeout=20,
        headers=ml_headers(),
    )
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return JSONResponse(status_code=r.status_code, content=data)

@app.get("/market/analysis")
def market_analysis(
    q: str,
    limit: int = 50,
    min_sold: int = 1,
    only_new: bool = True,
):
    r = requests.get(
        f"{BASE}/sites/MLA/search",
        params={"q": q, "limit": limit},
        timeout=20,
        headers=ml_headers(),
    )

    try:
        data = r.json()
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"error": "ml_non_json", "status_code": r.status_code, "raw": r.text},
        )

    # Si ML devuelve error con status != 200, lo mostramos
    if r.status_code != 200:
        return JSONResponse(
            status_code=r.status_code,
            content={"error": "ml_api_error", "ml_response": data, "ml_url": r.url},
        )

    items = data.get("results", [])

    # Debug duro si vienen 0 resultados
    if len(items) == 0:
        return {
            "error": "ml_zero_results",
            "q": q,
            "limit": limit,
            "min_sold": min_sold,
            "only_new": only_new,
            "ml_status_code": r.status_code,
            "ml_url": r.url,
            "ml_keys": list(data.keys()),
            "ml_paging": data.get("paging"),
            "ml_query": data.get("query"),
            "ml_sort": data.get("sort"),
            "ml_data_preview": data,
        }

    def ok_condition(i):
        return (i.get("condition") == "new") if only_new else True

    filtered = [
        i for i in items
        if i.get("price") is not None
        and ok_condition(i)
        and (i.get("sold_quantity") or 0) >= min_sold
    ]

    # diagnóstico si hay pocos datos
    if len(filtered) < 3:
        sample = [{
            "title": i.get("title"),
            "price": i.get("price"),
            "sold_quantity": i.get("sold_quantity"),
            "condition": i.get("condition"),
            "link": i.get("permalink")
        } for i in items[:10]]

        return {
            "error": "Not enough real sales data",
            "q": q,
            "limit": limit,
            "min_sold": min_sold,
            "only_new": only_new,
            "items_total": len(items),
            "items_after_filter": len(filtered),
            "sample_first_10": sample,
        }

    prices = [i["price"] for i in filtered]
    solds = [(i.get("sold_quantity") or 0) for i in filtered]

    # Si min_sold=0 puede haber sold_quantity=0 y dividir por 0 -> evitamos
    total_sold = sum(solds)
    if total_sold <= 0:
        return {
            "error": "No sold_quantity available to compute weighted average",
            "q": q,
            "items_analyzed": len(filtered),
            "hint": "Try min_sold=1 or higher",
        }

    weighted_avg = sum(p * s for p, s in zip(prices, solds)) / total_sold

    top_5 = sorted(filtered, key=lambda x: x.get("sold_quantity", 0), reverse=True)[:5]
    top_5_clean = [{
        "title": i.get("title"),
        "price": i.get("price"),
        "sold_quantity": i.get("sold_quantity"),
        "link": i.get("permalink")
    } for i in top_5]

    return {
        "q": q,
        "items_analyzed": len(filtered),
        "weighted_average_price": round(weighted_avg, 2),
        "min_price": min(prices),
        "max_price": max(prices),
        "top_5_best_sellers": top_5_clean,
    }
