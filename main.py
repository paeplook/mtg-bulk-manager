import os
from io import BytesIO
from typing import Optional, List
import pandas as pd
from fastapi import FastAPI, Query, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import create_engine, text

from init_db import init_db, get_database_url, CardInventory

app = FastAPI(title="MTG Collection Suite")
templates = Jinja2Templates(directory="templates")

database_url = get_database_url()
engine = create_engine(database_url)

@app.on_event("startup")
def startup_event():
    init_db()

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# API de búsqueda mejorada con Filtros de Rareza y Color
@app.get("/api/search")
def search_cards(
    q: str = Query(..., min_length=2),
    rarity: Optional[str] = Query(None), # e.g. "common,rare"
    colors: Optional[str] = Query(None), # e.g. "W,U,B"
    location: Optional[str] = Query(None)
):
    sql_query = """
        SELECT 
            name,
            set_code,
            set_name,
            rarity,
            scryfall_id,
            location,
            is_deck,
            SUM(quantity) as total_quantity
        FROM cards_inventory
        WHERE LOWER(name) LIKE LOWER(:search_term)
    """
    params = {"search_term": f"%{q}%"}

    # Filtro por Rareza
    if rarity:
        rarities = [r.strip().lower() for r in rarity.split(",") if r.strip()]
        if rarities:
            sql_query += " AND LOWER(rarity) IN :rarities"
            params["rarities"] = tuple(rarities)

    # Filtro por Ubicación
    if location and location != "all":
        sql_query += " AND location = :location"
        params["location"] = location

    sql_query += """
        GROUP BY name, set_code, set_name, rarity, scryfall_id, location, is_deck
        ORDER BY name ASC
    """

    with engine.connect() as conn:
        result = conn.execute(text(sql_query), params).mappings().all()

    results = [dict(row) for row in result]
    return {"results": results}

@app.get("/api/locations")
def get_locations():
    query = text("SELECT DISTINCT location FROM cards_inventory ORDER BY location ASC")
    with engine.connect() as conn:
        result = conn.execute(query).scalars().all()
    return {"locations": list(result)}

@app.post("/api/upload")
async def upload_csv(
    file: UploadFile = File(...), 
    location: str = Form("Bulk General"), 
    is_deck: bool = Form(False)
):
    try:
        contents = await file.read()
        df = pd.read_csv(BytesIO(contents))

        rename_mapping = {
            'Name': 'name',
            'Set code': 'set_code',
            'Set name': 'set_name',
            'Collector number': 'collector_number',
            'Foil': 'foil',
            'Rarity': 'rarity',
            'Quantity': 'quantity',
            'ManaBox ID': 'manabox_id',
            'Scryfall ID': 'scryfall_id',
            'Purchase price': 'purchase_price',
            'Misprint': 'misprint',
            'Altered': 'altered',
            'Condition': 'condition',
            'Language': 'language',
            'Purchase price currency': 'purchase_price_currency',
            'Added': 'added_at'
        }

        df = df.rename(columns=rename_mapping)
        df['location'] = location
        df['is_deck'] = is_deck

        if 'added_at' in df.columns:
            df['added_at'] = pd.to_datetime(df['added_at'], errors='coerce')

        allowed_cols = [c.name for c in CardInventory.__table__.columns if c.name != 'id']
        df_filtered = df[[col for col in df.columns if col in allowed_cols]]

        df_filtered.to_sql('cards_inventory', con=engine, if_exists='append', index=False, method='multi', chunksize=1000)

        return {"status": "success", "message": f"Se importaron {len(df_filtered)} registros correctamente en '{location}'."}

    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

@app.get("/api/stats")
def get_stats():
    query = text("""
        SELECT 
            COUNT(DISTINCT name) as unique_cards,
            COALESCE(SUM(quantity), 0) as total_cards,
            COUNT(DISTINCT location) as total_locations
        FROM cards_inventory
    """)
    with engine.connect() as conn:
        res = conn.execute(query).mappings().one()
    return dict(res)