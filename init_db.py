import os
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Float, ForeignKey, inspect, text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

def get_database_url():
    # URL directa de tu base de datos con el prefijo "postgresql://" corregido
    default_url = "postgresql://max:eqstHj4CR9mNS5n8dC2Ghd7y0Nth0gbNQZ2p5NXsbVev4KNGPaXeUhb2TyFGvk6m@sxslz0w9ehmdhleia2p18yxb:5432/mtg_db"
    
    # Intenta coger la de Coolify, si no la encuentra usa la tuya
    url = os.getenv("DATABASE_URL", default_url)
    
    # Parche de seguridad por si Coolify inyecta el formato antiguo
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
        
    return url

# 1. Tabla de Inventario Físico (ManaBox)
class CardInventory(Base):
    __tablename__ = 'cards_inventory'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, index=True)
    set_code = Column(String, nullable=False)
    set_name = Column(String)
    collector_number = Column(String)
    foil = Column(Boolean, default=False)
    rarity = Column(String)
    quantity = Column(Integer, default=1)
    scryfall_id = Column(String, index=True)
    market_price = Column(Float)
    location = Column(String, default="Bulk General")
    is_deck = Column(Boolean, default=False)

# 2. Tabla para Listas Teóricas (Brews)
class BrewedDeck(Base):
    __tablename__ = 'brewed_decks'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class BrewedDeckCard(Base):
    __tablename__ = 'brewed_deck_cards'

    id = Column(Integer, primary_key=True, autoincrement=True)
    deck_id = Column(Integer, ForeignKey('brewed_decks.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False)
    quantity = Column(Integer, default=1)
    set_code = Column(String)
    scryfall_id = Column(String)

def init_db():
    engine = create_engine(get_database_url())
    Base.metadata.create_all(engine)
    migrate_inventory_schema(engine)


def migrate_inventory_schema(engine):
    """Migra instalaciones existentes al modelo de inventario simplificado."""
    inspector = inspect(engine)
    if not inspector.has_table(CardInventory.__tablename__):
        return

    columns = {column["name"] for column in inspector.get_columns(CardInventory.__tablename__)}
    with engine.begin() as conn:
        # El valor antes llamado purchase_price se usaba como precio de Cardmarket.
        if "purchase_price" in columns and "market_price" not in columns:
            conn.execute(text("ALTER TABLE cards_inventory RENAME COLUMN purchase_price TO market_price"))
            columns.remove("purchase_price")
            columns.add("market_price")

        legacy_columns = {
            "manabox_id", "misprint", "altered", "condition", "language",
            "purchase_price_currency", "added_at",
        }
        for column in legacy_columns.intersection(columns):
            conn.execute(text(f"ALTER TABLE cards_inventory DROP COLUMN {column}"))

if __name__ == "__main__":
    init_db()
