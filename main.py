import os
import asyncio
import requests
from io import BytesIO
from typing import Optional, List
import pandas as pd
from fastapi import FastAPI, Query, Request, UploadFile, File, Form, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text
from apscheduler.schedulers.background import BackgroundScheduler

from init_db import init_db, get_database_url, CardInventory

app = FastAPI(title="MTG Collection Suite")

# Servir archivos estáticos (CSS, JS, imágenes)
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

database_url = get_database_url()
engine = create_engine(database_url)

def update_cardmarket_prices():
    print("🔄 [CRON MONDAY] Iniciando actualización semanal de precios de Cardmarket...")
    try:
        with engine.connect() as conn:
            query = text("SELECT DISTINCT scryfall_id FROM cards_inventory WHERE scryfall_id IS NOT NULL")
            unique_ids = conn.execute(query).scalars().all()

        updated_count = 0
        for scryfall_id in unique_ids:
            try:
                res = requests.get(f"https://api.scryfall.com/cards/{scryfall_id}", timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    prices = data.get("prices", {})
                    cmarket_price = prices.get("eur") or prices.get("eur_foil")

                    if cmarket_price:
                        cmarket_price = float(cmarket_price)
                        with engine.begin() as conn:
                            conn.execute(
                                text("UPDATE cards_inventory SET purchase_price = :price WHERE scryfall_id = :id"),
                                {"price": cmarket_price, "id": scryfall_id}
                            )
                        updated_count += 1
                asyncio.run(asyncio.sleep(0.1))
            except Exception:
                continue

        print(f"✅ [CRON MONDAY] Precios de Cardmarket actualizados con éxito en {updated_count} cartas.")
    except Exception as e:
        print(f"❌ Error durante la actualización de precios: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(update_cardmarket_prices, 'cron', day_of_week='mon', hour=0, minute=0)

@app.on_event("startup")
def startup_event():
    init_db()
    scheduler.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/update-prices")
def force_price_update(background_tasks: BackgroundTasks):
    background_tasks.add_task(update_cardmarket_prices)
    return {"status": "success", "message": "Actualización de precios de Cardmarket iniciada en segundo plano."}

@app.get("/api/search")
def search_cards(
    q: Optional[str] = Query(""),
    rarity: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("name_asc"),
    limit: int = Query(120)
):
    sql_query = """
        SELECT 
            name,
            set_code,
            set_name,
            collector_number,
            rarity,
            scryfall_id,
            location,
            is_deck,
            MAX(purchase_price) as purchase_price,
            SUM(quantity) as total_quantity
        FROM cards_inventory
        WHERE 1=1
    """
    params = {}

    if q and q.strip():
        sql_query += " AND LOWER(name) LIKE LOWER(:search_term)"
        params["search_term"] = f"%{q.strip()}%"

    if rarity:
        rarities = [r.strip().lower() for r in rarity.split(",") if r.strip()]
        if rarities:
            sql_query += " AND LOWER(rarity) IN :rarities"
            params["rarities"] = tuple(rarities)

    if location and location != "all":
        sql_query += " AND location = :location"
        params["location"] = location

    sql_query += " GROUP BY name, set_code, set_name, collector_number, rarity, scryfall_id, location, is_deck "

    if sort_by == "name_desc":
        sql_query += " ORDER BY name DESC "
    elif sort_by == "price_desc":
        sql_query += " ORDER BY MAX(purchase_price) DESC NULLS LAST, name ASC "
    elif sort_by == "price_asc":
        sql_query += " ORDER BY MAX(purchase_price) ASC NULLS LAST, name ASC "
    else:
        sql_query += " ORDER BY name ASC "

    sql_query += " LIMIT :limit "
    params["limit"] = limit

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