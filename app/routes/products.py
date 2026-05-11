from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.models.product import Product
from app.database import get_session

router = APIRouter()

@router.get("/products")
def get_products(session: Session = Depends(get_session)):
    products = session.exec(select(Product)).all()
    return products

@router.get("/products/{product_id}")
def get_product(product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.post("/products")
def create_product(product: Product, session: Session = Depends(get_session)):
    session.add(product)
    session.commit()
    session.refresh(product)
    return product