from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter()

STORE = "https://mikisi.co"


@router.get("/checkout")
def meta_checkout(product_ids: str = "", quantities: str = "", coupon: str = ""):
    ids = [i.strip() for i in product_ids.split(",") if i.strip()]
    qtys = [q.strip() for q in quantities.split(",") if q.strip()]

    if not ids:
        return RedirectResponse(STORE)

    if len(ids) == 1:
        return RedirectResponse(f"{STORE}/products/{ids[0]}")

    # Multiple products — redirect to home with add-to-cart params
    pairs = [f"{ids[i]}:{qtys[i] if i < len(qtys) else 1}" for i in range(len(ids))]
    return RedirectResponse(f"{STORE}/?add={','.join(pairs)}")
