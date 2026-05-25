from sqlmodel import SQLModel, Session, create_engine, select
from app.models.user import User
from app.models.product import Product
from app.models.order import Order
from app.models.cart import CartItem
from app.models.agent import AgentMemory, AgentTask, MarketInsight, MonthlyVision, AgentLearning, AgentGoal
from app.models.signal import SystemSignal
from app.models.supplier import Supplier
from app.models.collection import Collection
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./users.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)


def create_db():
    SQLModel.metadata.create_all(engine)

    # Fix column types if needed
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE product ALTER COLUMN cj_sku TYPE varchar(200)"))
        conn.execute(text("ALTER TABLE product ALTER COLUMN cj_product_id TYPE varchar(200)"))
        conn.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS images varchar(2000)"))
        conn.commit()

    # Register default suppliers
    _register_default_suppliers()


def _register_default_suppliers():
    with Session(engine) as session:
        existing = session.exec(
            select(Supplier).where(Supplier.name == "CJDropshipping")
        ).first()
        if not existing:
            cj = Supplier(
                name="CJDropshipping",
                adapter_class="app.agents.suppliers.cj_adapter.CJAdapter",
                base_url="https://developers.cjdropshipping.com/api2.0/v1",
                api_key_env="CJ_API_KEY",
                is_active=True,
                supported_categories="Beauty,Hair,Jewelry,Skincare,Makeup",
                supported_countries="US,CA,GB,AU,TZ,KE,ZA,NG,GH",
                reliability_score=1.0
            )
            session.add(cj)
            session.commit()
            print("[DB] ✅ CJ Dropshipping registered as supplier")
        else:
            print("[DB] CJ Dropshipping already registered")


def get_session():
    with Session(engine) as session:
        yield session