from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# In-memory "database" for now
users_db = {}

# This defines the shape of data we expect from the client
class UserRequest(BaseModel):
    email: str
    password: str

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/register")
def register(user: UserRequest):
    if user.email in users_db:
        raise HTTPException(status_code=400, detail="Email already registered")
    users_db[user.email] = user.password
    return {"message": "User registered successfully"}

@app.post("/login")
def login(user: UserRequest):
    if user.email not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    if users_db[user.email] != user.password:
        raise HTTPException(status_code=401, detail="Incorrect password")
    return {"message": "Logged in successfully"}