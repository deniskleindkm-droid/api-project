from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select
from app.models.user import User, UserRequest
from app.auth_utils import hash_password, verify_password, create_access_token, verify_token
from app.rate_limiter import rate_limit
from app.database import get_session
from fastapi import Request
from pydantic import BaseModel
import random
import string
from datetime import datetime, timedelta

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# In-memory verification store — fast, no extra DB table needed
# { email: { code: "123456", expires: datetime, attempts: 0 } }
_verification_store = {}


def generate_code():
    return ''.join(random.choices(string.digits, k=6))


def send_verification_email(email: str, code: str):
    try:
        from app.agents.email_partner import send_email
        body = f"""
<!DOCTYPE html>
<html>
<body style="font-family:'Georgia',serif;background:#fdf9f6;margin:0;padding:40px;">
<div style="max-width:480px;margin:0 auto;background:white;padding:48px;">

    <div style="text-align:center;margin-bottom:32px;">
        <h1 style="font-family:'Georgia',serif;font-size:26px;font-weight:300;
                   letter-spacing:6px;color:#0e0e0e;text-transform:uppercase;">
            Mik<em style="color:#d4849c;font-style:italic;">i</em>si
        </h1>
    </div>

    <h2 style="font-family:'Georgia',serif;font-size:22px;font-weight:300;
               color:#0e0e0e;margin-bottom:12px;">
        Verify your email
    </h2>

    <p style="font-size:14px;color:#6b6b6b;line-height:1.8;margin-bottom:32px;">
        Welcome to Mikisi. Enter this code to complete your registration.
    </p>

    <div style="background:#f7f2ed;padding:28px;text-align:center;margin-bottom:32px;">
        <div style="font-family:'Georgia',serif;font-size:40px;font-weight:300;
                    letter-spacing:16px;color:#0e0e0e;">
            {code}
        </div>
        <div style="font-size:11px;color:#6b6b6b;margin-top:12px;letter-spacing:1px;">
            This code expires in 10 minutes
        </div>
    </div>

    <p style="font-size:12px;color:#d8d0c8;line-height:1.8;">
        If you didn't create a Mikisi account, you can safely ignore this email.
    </p>

    <div style="border-top:1px solid #ece5dd;margin-top:40px;padding-top:24px;text-align:center;">
        <p style="font-size:11px;color:#d8d0c8;letter-spacing:2px;text-transform:uppercase;">
            Look Elegant and Polished
        </p>
    </div>

</div>
</body>
</html>"""
        send_email(email, "Your Mikisi verification code", body, is_html=True)
        print(f"[Auth] ✅ Verification code sent to {email}")
    except Exception as e:
        print(f"[Auth] Email send error: {e}")


class VerifyRequest(BaseModel):
    email: str
    code: str


class ResendRequest(BaseModel):
    email: str


@router.post("/register")
def register(user: UserRequest, session: Session = Depends(get_session)):
    existing = session.exec(select(User).where(User.email == user.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = User(
        email=user.email,
        password=hash_password(user.password),
        full_name=user.full_name,
        is_verified=False
    )
    session.add(new_user)
    session.commit()

    # Generate and send verification code
    code = generate_code()
    _verification_store[user.email] = {
        "code": code,
        "expires": datetime.utcnow() + timedelta(minutes=10),
        "attempts": 0
    }
    send_verification_email(user.email, code)

    return {"message": "Account created. Please check your email for a verification code."}


@router.post("/verify-email")
def verify_email(request: VerifyRequest, session: Session = Depends(get_session)):
    email = request.email.lower().strip()
    code = request.code.strip()

    entry = _verification_store.get(email)
    if not entry:
        raise HTTPException(status_code=400, detail="No verification code found. Please register again.")

    # Check expiry
    if datetime.utcnow() > entry["expires"]:
        del _verification_store[email]
        raise HTTPException(status_code=400, detail="Code has expired. Please request a new one.")

    # Check attempts
    if entry["attempts"] >= 5:
        raise HTTPException(status_code=400, detail="Too many attempts. Please request a new code.")

    entry["attempts"] += 1

    if entry["code"] != code:
        raise HTTPException(status_code=400, detail="Invalid code. Please try again.")

    # Mark user as verified
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_verified = True
    session.add(user)
    session.commit()

    # Clean up
    del _verification_store[email]
    print(f"[Auth] ✅ Email verified: {email}")

    return {"message": "Email verified successfully"}


@router.post("/resend-verification")
def resend_verification(request: ResendRequest, session: Session = Depends(get_session)):
    email = request.email.lower().strip()

    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_verified:
        raise HTTPException(status_code=400, detail="Email already verified")

    code = generate_code()
    _verification_store[email] = {
        "code": code,
        "expires": datetime.utcnow() + timedelta(minutes=10),
        "attempts": 0
    }
    send_verification_email(email, code)

    return {"message": "New verification code sent"}


@router.post("/login")
def login(user: UserRequest, request: Request, session: Session = Depends(get_session), _=Depends(rate_limit)):
    db_user = session.exec(select(User).where(User.email == user.email)).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(user.password, db_user.password):
        raise HTTPException(status_code=401, detail="Incorrect password")

    # Block unverified users from logging in
    if hasattr(db_user, 'is_verified') and db_user.is_verified is False:
        raise HTTPException(status_code=403, detail="Please verify your email before signing in")

    token = create_access_token({
        "sub": user.email,
        "name": db_user.full_name or user.email.split("@")[0]
    })
    return {
        "access_token": token,
        "token_type": "bearer",
        "full_name": db_user.full_name or user.email.split("@")[0]
    }


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