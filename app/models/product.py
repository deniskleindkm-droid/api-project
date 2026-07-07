from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    brand: str
    category: str
    description: str
    original_price: float
    discount_percent: float = 0.0
    final_price: float
    image_url: Optional[str] = None
    images: Optional[str] = None
    stock: int = 0
    supplier_name: Optional[str] = None
    supplier_url: Optional[str] = None
    shipping_days: int = 7
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    collection_id: Optional[int] = Field(default=None, foreign_key="collection.id")
    cj_product_id: Optional[str] = None
    cj_sku: Optional[str] = None
    variants: Optional[str] = Field(default=None)
    # Silverbene display fields
    material: Optional[str] = None
    sizes: Optional[str] = None
    colors: Optional[str] = None
    specs: Optional[str] = None  # JSON extracted from raw Silverbene desc before ARIA rewrites it
    # Pricing internals — never expose to frontend
    silverbene_cost: Optional[float] = None
    markup_used: Optional[float] = None
    # Pricing metadata
    shipping_cost: Optional[float] = None
    last_price_sync: Optional[datetime] = None
    # Product flags
    is_published: Optional[bool] = Field(default=True)   # False = staging; True = live on storefront; NULL treated as True
    stock_auto_unpublished: bool = Field(default=False)  # True = system hid this due to OOS; auto-republish on restock
    sync_miss_count: int = Field(default=0)              # consecutive stock sync misses; 3+ = discontinued at Silverbene
    is_premium: bool = False
    needs_review: bool = False
    needs_length_review: bool = False
    # Generated content — Cloudinary URLs only, never fal.ai/Runway (they expire)
    content_image_url: Optional[str] = None      # clean product shot
    content_lifestyle_url: Optional[str] = None  # lifestyle shot (skin tone rotated)
    video_url: Optional[str] = None              # product video
    content_generated_at: Optional[datetime] = None
    # Pinterest
    pinterest_pin_id: Optional[str] = None
    pinterest_synced_at: Optional[datetime] = None
    pinterest_catalog_id: Optional[str] = None


class ProductPublic(SQLModel):
    """Safe response model — silverbene_cost and markup_used are never included."""
    id: Optional[int] = None
    name: str
    brand: str
    category: str
    description: str
    original_price: float
    discount_percent: float = 0.0
    final_price: float
    image_url: Optional[str] = None
    images: Optional[str] = None
    stock: int = 0
    supplier_name: Optional[str] = None
    supplier_url: Optional[str] = None
    shipping_days: int = 7
    is_active: bool = True
    is_published: Optional[bool] = True
    created_at: Optional[datetime] = None
    collection_id: Optional[int] = None
    cj_product_id: Optional[str] = None
    cj_sku: Optional[str] = None
    variants: Optional[str] = None
    material: Optional[str] = None
    sizes: Optional[str] = None
    colors: Optional[str] = None
    specs: Optional[str] = None
    shipping_cost: Optional[float] = None
    last_price_sync: Optional[datetime] = None
    is_premium: bool = False
    needs_review: bool = False
    needs_length_review: bool = False
    content_image_url: Optional[str] = None
    content_lifestyle_url: Optional[str] = None
    video_url: Optional[str] = None
    content_generated_at: Optional[datetime] = None
    # Computed display metadata — populated by route, never stored in DB
    size_label: Optional[str] = None        # "Bracelet Length", "Chain Length", "Ring Size", …
    size_hint: Optional[str] = None         # one-line measurement guidance for the customer
    size_display_mode: Optional[str] = None # "selector" | "adjustable_badge" | "open_badge" | "none"


class ProductCreate(SQLModel):
    name: str
    brand: str
    category: str
    description: str
    original_price: float
    discount_percent: float = 0.0
    final_price: float
    image_url: Optional[str] = None
    images: Optional[str] = None
    stock: int = 0
    supplier_name: Optional[str] = None
    supplier_url: Optional[str] = None
    shipping_days: int = 7
    cj_product_id: Optional[str] = None
    cj_sku: Optional[str] = None
    material: Optional[str] = None
    sizes: Optional[str] = None
    colors: Optional[str] = None
