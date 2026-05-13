from sqlmodel import SQLModel, Session, create_engine
from app.models.user import User
from app.models.product import Product
from app.models.order import Order
from app.models.cart import CartItem
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./users.db")

# Fix for Railway PostgreSQL URL format
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

def create_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session