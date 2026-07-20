from sqlmodel import SQLModel, Field, UniqueConstraint
from typing import Optional
from datetime import datetime


class ProductVariant(SQLModel, table=True):
    """
    One row per real, priced Silverbene option — the canonical internal
    variant identity. `id` is the ONE thing carried through cart, order, and
    the Meta/Instagram catalog; `supplier_option_id` is read only at the
    point of actually calling Silverbene's place_order(), never compared or
    stored anywhere else.

    `size`/`color` are the FINAL, already-normalized display strings (same
    values that land in Product.sizes/Product.colors) — never raw supplier
    text, never re-normalized by a caller. This is also the single source of
    truth the frontend displays and matches against directly, replacing the
    hand-duplicated raw-to-display mapping that used to live independently
    in silverbene_adapter.py (_METAL_COLOR_NORMALIZE) and docs/index.html
    (COLOR_LABEL) and could silently disagree between the two.

    `available` is a soft-delete flag only — mirrors the existing invariant
    in silverbene_stock_agent.py's _reconcile_variant_availability(), which
    never removes an option once Silverbene stops listing it, only flips
    this to False. `sort_order` preserves the implicit "first variant"
    ordering today's JSON array order provides, for the Pass-4/fallback
    behavior that depends on it.
    """
    __tablename__ = "product_variant"
    __table_args__ = (
        UniqueConstraint("product_id", "supplier_name", "supplier_option_id",
                          name="uq_variant_product_supplier_option"),
    )

    id:                  Optional[int] = Field(default=None, primary_key=True)
    product_id:          int           = Field(foreign_key="product.id", index=True)

    supplier_name:       str           = Field(default="Silverbene", index=True)
    supplier_option_id:  str           = Field(index=True)

    size:                Optional[str] = None
    color:               Optional[str] = None
    raw_attributes:      Optional[str] = None   # JSON of this option's raw {name,value} list — audit/debug only

    base_price:          float         = 0.0
    final_price:         float         = 0.0
    stock:               int           = 0
    available:           bool          = True
    sort_order:          int           = 0

    created_at:          datetime      = Field(default_factory=datetime.utcnow)
    last_synced_at:      Optional[datetime] = None
