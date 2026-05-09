from fastapi import FastAPI
from app.routes.auth import router as auth_router
from app.database import create_db
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

app = FastAPI(title=os.getenv("APP_NAME", "MyAPI"))

@app.on_event("startup")
def on_startup():
    create_db()

app.include_router(auth_router)

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": os.getenv("APP_NAME", "MyAPI")
    }