from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.collection import Collection
from app.models.product import Product
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()

class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: int = 0

class CollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None

@router.get("/collections")
def get_collections(session: Session = Depends(get_session)):
    collections = session.exec(
        select(Collection).where(Collection.is_active == True)
        .order_by(Collection.sort_order)
    ).all()
    
    def build_tree(parent_id=None):
        children = [c for c in collections if c.parent_id == parent_id]
        result = []
        for col in children:
            products = session.exec(
                select(Product).where(
                    Product.collection_id == col.id,
                    Product.is_active == True
                )
            ).all()
            result.append({
                "id": col.id,
                "name": col.name,
                "description": col.description,
                "image_url": col.image_url,
                "parent_id": col.parent_id,
                "sort_order": col.sort_order,
                "product_count": len(products),
                "children": build_tree(col.id)
            })
        return result
    
    return build_tree(None)

@router.post("/collections")
def create_collection(
    data: CollectionCreate,
    session: Session = Depends(get_session)
):
    collection = Collection(
    name=data.name,
    description=data.description,
    image_url=data.image_url,
    parent_id=data.parent_id if data.parent_id and data.parent_id > 0 else None,
    sort_order=data.sort_order,
    is_active=True,
    created_at=datetime.utcnow()
)
    session.add(collection)
    session.commit()
    session.refresh(collection)
    return collection

@router.put("/collections/{collection_id}")
def update_collection(
    collection_id: int,
    data: CollectionUpdate,
    session: Session = Depends(get_session)
):
    collection = session.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    
    if data.name is not None:
        collection.name = data.name
    if data.description is not None:
        collection.description = data.description
    if data.image_url is not None:
        collection.image_url = data.image_url
    if data.parent_id is not None:
        collection.parent_id = data.parent_id
    if data.sort_order is not None:
        collection.sort_order = data.sort_order
    if data.is_active is not None:
        collection.is_active = data.is_active
    
    session.add(collection)
    session.commit()
    session.refresh(collection)
    return collection

@router.delete("/collections/{collection_id}")
def delete_collection(
    collection_id: int,
    session: Session = Depends(get_session)
):
    collection = session.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    collection.is_active = False
    session.add(collection)
    session.commit()
    return {"deleted": True}

@router.get("/collections/{collection_id}/products")
def get_collection_products(
    collection_id: int,
    session: Session = Depends(get_session)
):
    collection = session.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    
    products = session.exec(
        select(Product).where(
            Product.collection_id == collection_id,
            Product.is_active == True
        )
    ).all()
    return products