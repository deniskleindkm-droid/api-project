from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/checkout")
def meta_checkout():
    return FileResponse("docs/checkout.html")
