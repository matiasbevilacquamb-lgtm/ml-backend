from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import os
import time
import requests

app = FastAPI()

BASE = "https://api.mercadolibre.com"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"

# =============================
# HEADERS
# =============================

def ml_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Render) ml-backend/1.0",
        "Accept": "application/json",
    }

def ml_headers_auth():
    token = get_access_token()
    return {
        "User-Agent": "Mozilla/5.0 (Render) ml-backend/1.0",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

# =============================
# TOKEN MANAGEMENT
# =============================

_token_cache = {
    "access_token": None,
    "expires_at": 0,
}

def refresh_access_token():
    client_id = os.getenv("ML_CLIENT_ID")
    client_secret = os.getenv("ML_CLIENT_SECRET")
    refresh_token = os.getenv("ML_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError("Missing ML credentials")

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

    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = int(time.time()) + expires_in - 60

    return access_token


def get_access_token():
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]
    return refresh_access_token()

# =============================
# TEST AUTH
# =============================

@app.get("/ml/test-auth")
def ml_test_auth():
    token = get_access_token()

    r = requests.get(
        f"{BASE}/users/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )

    return {
        "status_code": r.status_code,
        "response": r.json()
    }

# =============================
# MARKET ANALYSIS
# =============================

@app.get("/market/analysis")
def market_analysis(
    q: str,
    limit: int = 50,
    min_sold: int = 1,
    only_new: bool = True,
):
    # intento sin auth
    r = requests.get(
        f"{BASE}/sites/MLA/search",
        params={"q": q, "limit": limit},
        timeout=20,
        headers=ml_headers(),
    )

    # si ML bloquea → reintento autenticado
    if r.status_code == 403:
        r = requests.get(
            f"{BASE}/sites/MLA/search",
            params={"q": q, "limit": limit},
            timeout=20,
            headers=ml_headers_auth(),
        )

    try:
        data = r.json()
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"error": "ml_non_json", "raw": r.text},
        )

    if r.status_code != 200:
        return JSONResponse(
            status_code=r.status_code,
            content={"error": "ml_api_error", "ml_response": data},
        )

    items = data.get("results", [])

    if len(items) == 0:
        return {
            "error": "ml_zero_results",
            "ml_url": r.url,
            "ml_response": data,
        }

    def ok_condition(i):
        return (i.get("condition") == "new") if only_new else True

    filtered = [
        i for i in items
        if i.get("price") is not None
        and ok_condition(i)
        and (i.get("sold_quantity") or 0) >= min_sold
    ]

    if len(filtered) < 3:
        return {
            "error": "Not enough real sales data",
            "items_total": len(items),
            "items_after_filter": len(filtered),
        }

    prices = [i["price"] for i in filtered]
    solds = [(i.get("sold_quantity") or 0) for i in filtered]

    total_sold = sum(solds)
    if total_sold == 0:
        return {"error": "No sold_quantity data"}

    weighted_avg = sum(p * s for p, s in zip(prices, solds)) / total_sold

    top_5 = sorted(filtered, key=lambda x: x.get("sold_quantity", 0), reverse=True)[:5]

    return {
        "items_analyzed": len(filtered),
        "weighted_average_price": round(weighted_avg, 2),
        "min_price": min(prices),
        "max_price": max(prices),
        "top_5": [
            {
                "title": i.get("title"),
                "price": i.get("price"),
                "sold_quantity": i.get("sold_quantity"),
            }
            for i in top_5
        ],
    }
from fastapi import Body

@app.post("/market/analyze-results")
def analyze_results(payload: dict = Body(...)):
    """
    Recibe el JSON de Mercado Libre (response de /sites/MLA/search)
    y devuelve análisis: promedio ponderado, min/max, top sellers.
    """
    items = payload.get("results", [])
    if not items:
        return {"error": "No results provided", "items_total": 0}

    # Parámetros opcionales (si vienen en payload.meta)
    meta = payload.get("meta", {}) or {}
    min_sold = int(meta.get("min_sold", 1))
    only_new = bool(meta.get("only_new", True))

    def ok_condition(i):
        return (i.get("condition") == "new") if only_new else True

    filtered = [
        i for i in items
        if i.get("price") is not None
        and ok_condition(i)
        and (i.get("sold_quantity") or 0) >= min_sold
    ]

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
            "items_total": len(items),
            "items_after_filter": len(filtered),
            "min_sold": min_sold,
            "only_new": only_new,
            "sample_first_10": sample
        }

    prices = [i["price"] for i in filtered]
    solds = [(i.get("sold_quantity") or 0) for i in filtered]
    total_sold = sum(solds)

    if total_sold <= 0:
        return {
            "error": "No sold_quantity available to compute weighted average",
            "items_analyzed": len(filtered),
            "hint": "Try min_sold=1 or higher"
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
        "items_analyzed": len(filtered),
        "weighted_average_price": round(weighted_avg, 2),
        "min_price": min(prices),
        "max_price": max(prices),
        "top_5_best_sellers": top_5_clean
    }
