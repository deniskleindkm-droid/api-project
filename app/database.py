from sqlmodel import SQLModel, Session, create_engine
from app.models.user import User
from app.models.product import Product
from app.models.order import Order
from app.models.cart import CartItem

DATABASE_URL = "sqlite:///./users.db"

engine = create_engine(DATABASE_URL, echo=True)

def create_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session