import os
import re
import asyncio
import requests
from io import BytesIO
from typing import Optional
import pandas as pd
from fastapi import FastAPI, Query, Request, UploadFile, File, Form, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler

from init_db import init_db, get_database_url, CardInventory, BrewedDeck, BrewedDeckCard

app = FastAPI(title="MTG Collection Suite")
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

database_url = get_database_url()
engine = create_engine(database_url)

# --- TAREAS EN SEGUNDO PLANO ---
def update_cardmarket_prices():
    # Tu código actual de actualización semanal...
    pass

scheduler = BackgroundScheduler()
scheduler.add_job(update_cardmarket_prices, 'cron', day_of_week='mon', hour=0, minute=0)

@app.on_event("startup")
def startup_event():
    init_db()
    scheduler.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

# --- RUTAS PRINCIPALES ---
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# --- API DE MAZOS HÍBRIDOS ---
@app.get("/api/decks/physical")
def get_physical_decks():
    sql = """
        SELECT location as name, SUM(quantity) as total_cards
        FROM cards_inventory WHERE is_deck = true GROUP BY location
    """
    with engine.connect() as conn:
        result = conn.execute(text(sql)).mappings().all()
    return {"decks": [dict(r) for r in result]}

class DeckImportSchema(BaseModel):
    name: str
    decklist: str

@app.post("/api/decks/import-text")
def import_text_deck(data: DeckImportSchema):
    patron = re.compile(r"^(\d+)x?\s+(.+?)(?:\s+\(([A-Za-z0-9]+)\))?(?:\s+\d+)?$")
    lineas = data.decklist.strip().split('\n')
    
    with engine.begin() as conn:
        deck_id = conn.execute(
            text("INSERT INTO brewed_decks (name) VALUES (:name) RETURNING id"), 
            {"name": data.name}
        ).scalar()

        for linea in lineas:
            linea = linea.strip()
            if not linea: continue
            match = patron.match(linea)
            if match:
                qty = int(match.group(1))
                name = match.group(2).strip()
                set_code = match.group(3).lower() if match.group(3) else None

                try:
                    if set_code:
                        url = f"https://api.scryfall.com/cards/named?exact={name}&set={set_code}"
                        res = requests.get(url).json()
                    else:
                        url = f"https://api.scryfall.com/cards/search?q=!\"{name}\"&order=released&dir=desc"
                        search_res = requests.get(url).json()
                        res = search_res.get("data", [{}])[0] if "data" in search_res else {}

                    scryfall_id = res.get("id", "")
                    final_set = res.get("set", set_code)

                    conn.execute(text("""
                        INSERT INTO brewed_deck_cards (deck_id, name, quantity, set_code, scryfall_id)
                        VALUES (:d_id, :name, :qty, :set_code, :s_id)
                    """), {"d_id": deck_id, "name": name, "qty": qty, "set_code": final_set, "s_id": scryfall_id})
                except Exception as e:
                    print(f"Error procesando {name}: {e}")

    return {"status": "success"}

@app.get("/api/decks/brews")
def get_brewed_decks():
    sql = """
        SELECT d.id, d.name, COALESCE(SUM(c.quantity), 0) as total_cards
        FROM brewed_decks d
        LEFT JOIN brewed_deck_cards c ON d.id = c.deck_id
        GROUP BY d.id ORDER BY d.created_at DESC
    """
    with engine.connect() as conn:
        result = conn.execute(text(sql)).mappings().all()
    return {"decks": [dict(r) for r in result]}

# (Mantén aquí el resto de tus rutas de /api/search, /api/upload y /api/stats iguales)