from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select
from app.models.user import User, UserRequest
from app.auth_utils import hash_password, verify_password, create_access_token, verify_token
from app.rate_limiter import rate_limit
from app.database import get_session
from fastapi import Request

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

@router.post("/register")
def register(user: UserRequest, session: Session = Depends(get_session)):
    existing_user = session.exec(select(User).where(User.email == user.email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = User(
        email=user.email,
        password=hash_password(user.password),
        full_name=user.full_name
    )
    session.add(new_user)
    session.commit()
    return {"message": "User registered successfully"}

@router.post("/login")
def login(user: UserRequest, request: Request, session: Session = Depends(get_session), _=Depends(rate_limit)):
    db_user = session.exec(select(User).where(User.email == user.email)).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(user.password, db_user.password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    token = create_access_token({"sub": user.email, "name": db_user.full_name or user.email.split("@")[0]})
    return {"access_token": token, "token_type": "bearer", "full_name": db_user.full_name or user.email.split("@")[0]}

@router.get("/profile")
def get_profile(token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"email": payload.get("sub"), "name": payload.get("name"), "message": "Welcome to your profile!"}

@router.get("/users")
def get_users(session: Session = Depends(get_session)):
    users = session.exec(select(User)).all()
    return [{"id": user.id, "email": user.email, "full_name": user.full_name} for user in users]