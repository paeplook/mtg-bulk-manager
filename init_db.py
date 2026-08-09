import os
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

def get_database_url():
    return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/mtg_db")

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
    manabox_id = Column(String)
    scryfall_id = Column(String, index=True)
    purchase_price = Column(Float)
    misprint = Column(Boolean, default=False)
    altered = Column(Boolean, default=False)
    condition = Column(String)
    language = Column(String)
    purchase_price_currency = Column(String)
    added_at = Column(DateTime, default=datetime.utcnow)
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

if __name__ == "__main__":
    init_db()