from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routes.auth import router as auth_router
from app.routes.products import router as products_router
from app.routes.orders import router as orders_router
from app.routes.cart import router as cart_router
from app.database import create_db
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

app = FastAPI(title=os.getenv("APP_NAME", "MyAPI"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    create_db()

app.include_router(auth_router)
app.include_router(products_router)
app.include_router(orders_router)
app.include_router(cart_router)

@app.get("/")
def serve_frontend():
    return FileResponse("docs/index.html")

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": os.getenv("APP_NAME", "MyAPI")
    }