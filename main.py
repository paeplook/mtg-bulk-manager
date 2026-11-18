import os
import re
import requests
import time
from datetime import datetime
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
    with engine.begin() as conn:
        result = conn.execute(text("SELECT DISTINCT scryfall_id FROM cards_inventory WHERE scryfall_id IS NOT NULL")).fetchall()
        for row in result:
            s_id = row[0]
            try:
                res = requests.get(f"https://api.scryfall.com/cards/{s_id}").json()
                price = res.get("prices", {}).get("eur")
                if price:
                    conn.execute(
                        text("UPDATE cards_inventory SET market_price = :price WHERE scryfall_id = :s_id"),
                        {"price": float(price), "s_id": s_id}
                    )
                time.sleep(0.1)
            except Exception as e:
                print(f"Error actualizando precio para {s_id}: {e}")

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

# --- API DE ESTADÍSTICAS ---
@app.get("/api/stats")
def get_stats():
    with engine.connect() as conn:
        unique_cards = conn.execute(text("SELECT COUNT(DISTINCT scryfall_id) FROM cards_inventory")).scalar() or 0
        total_cards = conn.execute(text("SELECT SUM(quantity) FROM cards_inventory")).scalar() or 0
        total_locations = conn.execute(text("SELECT COUNT(DISTINCT location) FROM cards_inventory")).scalar() or 0
    return {
        "unique_cards": unique_cards,
        "total_cards": total_cards,
        "total_locations": total_locations
    }

# --- API DE BÚSQUEDA Y COLECCIÓN ---
@app.get("/api/search")
def search_cards(
    q: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("name_asc"),
    rarity: Optional[str] = Query(None),
    colors: Optional[str] = Query(None)
):
    sql = """
        SELECT 
            scryfall_id, 
            name, 
            set_code, 
            set_name, 
            collector_number, 
            rarity, 
            market_price,
            location, 
            is_deck,
            SUM(quantity) as total_quantity
        FROM cards_inventory
        WHERE 1=1
    """
    params = {}

    if q:
        sql += " AND name ILIKE :q"
        params["q"] = f"%{q}%"

    if rarity:
        rarities_list = rarity.split(",")
        sql += " AND rarity = ANY(:rarities)"
        params["rarities"] = rarities_list

    sql += " GROUP BY scryfall_id, name, set_code, set_name, collector_number, rarity, market_price, location, is_deck"

    if sort_by == "name_asc":
        sql += " ORDER BY name ASC"
    elif sort_by == "name_desc":
        sql += " ORDER BY name DESC"
    elif sort_by == "price_desc":
        sql += " ORDER BY market_price DESC NULLS LAST"
    elif sort_by == "price_asc":
        sql += " ORDER BY market_price ASC NULLS LAST"

    with engine.connect() as conn:
        result = conn.execute(text(sql), params).mappings().all()

    return {"results": [dict(row) for row in result]}

# --- API DE SUBIDA DE CSV (MANABOX) ---
@app.post("/api/upload")
async def upload_csv(
    file: UploadFile = File(...),
    location: str = Form(...),
    is_deck: bool = Form(False)
):
    try:
        contents = await file.read()
        df = pd.read_csv(pd.io.common.BytesIO(contents))
        
        # Normalizar columnas comunes de ManaBox
        col_map = {c.lower(): c for c in df.columns}
        
        with engine.begin() as conn:
            for _, row in df.iterrows():
                name = row.get(col_map.get('name', 'name'), 'Unknown')
                set_code = str(row.get(col_map.get('set code', 'set_code'), ''))
                set_name = str(row.get(col_map.get('set name', 'set_name'), ''))
                collector_number = str(row.get(col_map.get('collector number', 'collector_number'), ''))
                quantity = int(row.get(col_map.get('quantity', 'quantity'), 1))
                foil = str(row.get(col_map.get('foil', 'foil'), '')).lower() == 'true'
                rarity = str(row.get(col_map.get('rarity', 'rarity'), 'common'))
                scryfall_id = str(row.get(col_map.get('scryfall id', 'scryfall_id'), ''))

                conn.execute(text("""
                    INSERT INTO cards_inventory (
                        name, set_code, set_name, collector_number, quantity, 
                        foil, rarity, scryfall_id,
                        location, is_deck
                    ) VALUES (
                        :name, :set_code, :set_name, :collector_number, :quantity,
                        :foil, :rarity, :scryfall_id,
                        :location, :is_deck
                    )
                """), {
                    "name": name, "set_code": set_code, "set_name": set_name,
                    "collector_number": collector_number, "quantity": quantity,
                    "foil": foil, "rarity": rarity, "scryfall_id": scryfall_id,
                    "location": location, "is_deck": is_deck
                })

        return {"message": "Colección importada correctamente con éxito."}
    except Exception as e:
        return JSONResponse(status_code=400, content={"message": str(e)})

# --- API DE ACTUALIZACIÓN MANUAL DE PRECIOS ---
@app.post("/api/update-prices")
def manual_update_prices(background_tasks: BackgroundTasks):
    background_tasks.add_task(update_cardmarket_prices)
    return {"message": "Actualización de precios en segundo plano iniciada."}

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
# --- NUEVAS RUTAS PARA VER EL DETALLE DE UN MAZO ---
@app.get("/api/decks/physical/{location}")
def get_physical_deck_cards(location: str):
    sql = """
        SELECT scryfall_id, name, set_code, set_name, collector_number, rarity, market_price, location, is_deck, SUM(quantity) as total_quantity
        FROM cards_inventory
        WHERE location = :location AND is_deck = true
        GROUP BY scryfall_id, name, set_code, set_name, collector_number, rarity, market_price, location, is_deck
    """
    with engine.connect() as conn:
        result = conn.execute(text(sql), {"location": location}).mappings().all()
    return {"cards": [dict(r) for r in result]}

@app.get("/api/decks/brews/{deck_id}")
def get_brewed_deck_cards(deck_id: int):
    sql = """
        SELECT scryfall_id, name, set_code, quantity as total_quantity, 0 as market_price
        FROM brewed_deck_cards
        WHERE deck_id = :deck_id
    """
    with engine.connect() as conn:
        result = conn.execute(text(sql), {"deck_id": deck_id}).mappings().all()
    return {"cards": [dict(r) for r in result]}
