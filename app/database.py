from sqlmodel import SQLModel, Session, create_engine
from app.models.user import User
from app.models.product import Product
from app.models.order import Order
from app.models.cart import CartItem
from app.models.agent import AgentMemory, AgentTask, MarketInsight, MonthlyVision, AgentLearning, AgentGoal
from app.models.collection import Collection
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./users.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

def create_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

def create_db():
    SQLModel.metadata.create_all(engine)
    # Fix column types if needed
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE product ALTER COLUMN cj_sku TYPE varchar(200)"))
        conn.execute(text("ALTER TABLE product ALTER COLUMN cj_product_id TYPE varchar(200)"))
        conn.commit()        