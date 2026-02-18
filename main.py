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

from fastapi import FastAPI, Query
import requests

app = FastAPI()

BASE = "https://api.mercadolibre.com"

@app.get("/sites/MLA")
def get_site():
    r = requests.get(f"{BASE}/sites/MLA", timeout=20)
    return r.json()

@app.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = 20):
    params = {"q": q, "limit": limit}
    r = requests.get(f"{BASE}/sites/MLA/search", params=params, 
timeout=20)
    return r.json()

