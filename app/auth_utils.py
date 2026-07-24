from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import os

SECRET_KEY = os.getenv("SECRET_KEY", "mysupersecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour -- per Dennis 2026-07-24: sessions
# should end 1 hour after the customer goes INACTIVE, not stay alive for a
# flat 24h regardless of activity (that was the previous fix, 2026-07-23,
# for a different bug -- see git history). This 60-minute token lifetime is
# only half the mechanism: docs/index.html tracks real user activity and
# calls POST /refresh (see routes/auth.py) every few minutes to reissue
# a fresh 1-hour token WHILE the customer is active. If they go quiet, no
# refresh call fires, this token expires on schedule, and the 401 handling
# already wired into every authenticated fetch (_sessionExpired(), added
# 2026-07-23) logs them out cleanly on their next action.

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return token

def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        return None