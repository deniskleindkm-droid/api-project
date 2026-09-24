"""
Pre-payment cart validation: Mikisi product/variant -> Silverbene option_id ->
quantity -> live stock. Catches a missing ring size / color / unavailable
option BEFORE the customer pays, not after the autonomous agent has already
tried to create the supplier order.

Resolution order mirrors payments.process_order_background (so the option a
customer is quoted is the option that later gets ordered):
  1. variant_id (must belong to the product),
  2. selected_option_id (must appear among the product's own variants),
  3. resolve_option_id(size, color),
  4. product.cj_sku ONLY when the product has a single purchasable option;
     a multi-option product with no resolvable selection is rejected.
"""
from __future__ import annotations

import json
from typing import List, Optional, Tuple

from sqlmodel import Session, select

from app.models.product import Product
from app.models.product_variant import ProductVariant


class ItemError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _variants_list(product: Product) -> list:
    try:
        return json.loads(product.variants or "[]")
    except Exception:
        return []


def resolve_line(session: Session, product: Product, line: dict) -> Tuple[str, Optional[int]]:
    """Returns (supplier_option_id, variant_id) or raises ItemError."""
    from app.agents.suppliers.silverbene_adapter import resolve_option_id

    variant_id = line.get("variant_id")
    if variant_id:
        v = session.get(ProductVariant, variant_id)
        if v and v.product_id == product.id and v.supplier_option_id:
            if getattr(v, "admin_hidden", False) or getattr(v, "available", True) is False:
                raise ItemError(f"'{product.name[:40]}' in that option is no longer available")
            return str(v.supplier_option_id), variant_id

    sel = line.get("selected_option_id")
    variants = _variants_list(product)
    if sel and any(str(x.get("option_id")) == str(sel) for x in variants):
        return str(sel), variant_id

    if line.get("selected_size") or line.get("selected_color"):
        resolved = resolve_option_id(
            product.variants, line.get("selected_size"), line.get("selected_color"))
        if resolved:
            return str(resolved), variant_id

    option_count = len(variants)
    rows = session.exec(select(ProductVariant).where(ProductVariant.product_id == product.id)).all()
    option_count = max(option_count, len(rows))
    if option_count <= 1 and product.cj_sku:
        return str(product.cj_sku), variant_id
    raise ItemError(f"Please choose a size / finish for '{product.name[:40]}'")


def validate_cart(session: Session, lines: List[dict], live_stock_check=None) -> List[dict]:
    """
    lines: [{product_id, quantity, variant_id?, selected_option_id?, selected_size?, selected_color?}]
    Returns validated lines with `supplier_option_id`. Raises ItemError with a
    customer-facing message on the first problem.
    """
    from app.agents.store_config import get_hidden_categories

    if not lines:
        raise ItemError("Your cart is empty")
    hidden = get_hidden_categories()
    out, stock_pairs = [], []
    for line in lines:
        qty = int(line.get("quantity") or 1)
        if qty < 1 or qty > 20:
            raise ItemError("Please choose a valid quantity")
        product = session.get(Product, line["product_id"])
        if (not product or not product.is_active or not product.is_published
                or product.category in hidden):
            raise ItemError(f"Product {line['product_id']} is no longer available")
        if product.stock == 0:
            raise ItemError(f"'{product.name[:40]}' is out of stock")
        option_id, variant_id = resolve_line(session, product, line)
        out.append({
            "product_id": product.id,
            "quantity": qty,
            "variant_id": variant_id,
            "selected_size": line.get("selected_size"),
            "selected_color": line.get("selected_color"),
            "selected_option_id": line.get("selected_option_id"),
            "supplier_option_id": option_id,
        })
        stock_pairs.append((product, option_id))

    if live_stock_check is None:
        from app.routes.payments import _live_stock_check_many as live_stock_check
    err = live_stock_check(stock_pairs)
    if err:
        raise ItemError(err)
    return out
