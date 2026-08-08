import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase

# URL por defecto con tus credenciales de PostgreSQL en Coolify
DEFAULT_DB_URL = "postgres://postgres:cvoObqvSN6hgUzrIn58hbKDo2zDWqLjv6cqiZCMfrIMnpXoWuYJDdbrggurpF8Xg@sxslz0w9ehmdhleia2p18yxb:5432/postgres"

class Base(DeclarativeBase):
    pass

class CardInventory(Base):
    __tablename__ = 'cards_inventory'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    set_code = Column(String(20), nullable=False)
    set_name = Column(String(255))
    collector_number = Column(String(50))
    foil = Column(String(20))
    rarity = Column(String(20))
    quantity = Column(Integer, nullable=False, default=1)
    manabox_id = Column(Integer)
    scryfall_id = Column(String(50), nullable=False, index=True)
    purchase_price = Column(Float)
    misprint = Column(Boolean, default=False)
    altered = Column(Boolean, default=False)
    condition = Column(String(50))
    language = Column(String(20))
    purchase_price_currency = Column(String(10))
    added_at = Column(TIMESTAMP)
    
    # Campos propios para gestión de Bulk / Mazos
    location = Column(String(100), nullable=False, default="Bulk General", index=True)
    is_deck = Column(Boolean, nullable=False, default=False)

def get_database_url():
    # Intenta leer de la variable de entorno, si no existe usa la URL por defecto
    database_url = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    
    # Corrección automática del driver para SQLAlchemy (postgres:// -> postgresql://)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        
    return database_url

def init_db():
    database_url = get_database_url()
    print("⏳ Conectando a PostgreSQL y creando tablas...")
    engine = create_engine(database_url)
    Base.metadata.create_all(bind=engine)
    print("✅ Tabla 'cards_inventory' creada con éxito.")

if __name__ == "__main__":
    init_db()