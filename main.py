
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

