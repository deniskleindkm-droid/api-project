"""
Local browser-QA harness for the international checkout. NOT production code.

  python scripts/dev_checkout_harness.py [--port 8123]

Serves docs/index.html (with its API constant pointed at this server) plus the real
intl-checkout and payments routers on a SCRATCH SQLite database (never the production
DATABASE_URL). Stripe uses the test key from .env (test sessions only, nothing charged).
Supplier rates are a scripted fake so every scenario is reproducible and instant/slow
on demand -- Silverbene's real rate endpoint takes 40-90 s.

Scenario switches (via the postcode, so the browser can drive them):
  00000 / 00 / ZZ-prefix   -> supplier returns no rates ("no shipping available")
  any other                -> normal rates for that country
Harness endpoints:  GET /__harness/expire/{checkout_id}  age the quote past its TTL
                    GET /__harness/reprice?express=NN     change EXPRESS supplier price for new quotes
                    GET /__harness/delay?seconds=N        make the fake supplier slow
"""
import argparse
import os
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

_scratch = os.path.join(tempfile.gettempdir(), "mikisi_harness.db")
if os.path.exists(_scratch):
    os.remove(_scratch)
os.environ["DATABASE_URL"] = f"sqlite:///{_scratch}"        # set BEFORE app imports; .env must not win
os.environ["INTL_CHECKOUT"] = "1"
os.environ["INTL_ENABLED_COUNTRIES"] = "US,GB,DE,FR,AU,CA"
os.environ.setdefault("INTL_TIER_EXPOSURE", "frozen")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))                      # does not override the vars above
assert os.environ["DATABASE_URL"].startswith("sqlite"), "harness must never touch a real database"
assert os.getenv("STRIPE_SECRET_KEY", "").startswith("sk_test_"), "harness requires a Stripe TEST key"

import json  # noqa: E402
import re  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

# PayPal SANDBOX: .env may name these "Paypal Client_ID" / "Paypal Secret_key" (invalid dotenv keys),
# so read them tolerantly here without ever printing them or editing .env.
def _read_paypal_from_env_file():
    found = {}
    for line in open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="replace"):
        m = re.match(r"\s*paypal[ _]*(client[ _]*id|secret[ _]*key|client[ _]*secret|webhook[ _]*id)\s*=\s*(.+?)\s*$", line, re.I)
        if m:
            kind = re.sub(r"[ _]", "", m.group(1).lower())
            found["PAYPAL_CLIENT_ID" if kind == "clientid" else
                  "PAYPAL_WEBHOOK_ID" if kind == "webhookid" else "PAYPAL_CLIENT_SECRET"] = m.group(2).strip().strip("\"'")
    return found

for _k, _v in _read_paypal_from_env_file().items():
    os.environ.setdefault(_k, _v)
os.environ["INTL_PAYPAL"] = "1"
os.environ["PAYPAL_MODE"] = "sandbox"                      # live is refused by the client anyway
os.environ["PUBLIC_API_BASE"] = f"http://127.0.0.1:{os.getenv('HARNESS_PORT', '8123')}"

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

import app.database as db  # noqa: E402
from app.checkout_intl import transaction as txn  # noqa: E402
from app.models.checkout_transaction import CheckoutTransaction  # noqa: E402
from app.models.product import Product  # noqa: E402

state = {"delay": 2.0, "express_price": 53.24}

RATES = {
    "US": lambda: [
        {"way": "DHLI", "title": "DHL Express(4 - 9 workdays, customs duty included)", "price": state["express_price"]},
        {"way": "FedexI", "title": "FedEx(4 - 9 workdays, customs duty included)", "price": 57.82},
        {"way": "ITDIDA_ECO", "title": "International Economy(10-15 workdays)", "price": 3.5},
        {"way": "ITDIDA_ECO", "title": "International Standard(12-20 workdays)", "price": 5.52}],
    "GB": lambda: [
        {"way": "HERMES", "title": "Hermes(4-10 workdays)", "price": 3.46},
        {"way": "DHLI", "title": "DHL Express(3-7 workdays)", "price": state["express_price"]}],
    "DE": lambda: [
        {"way": "DHLGM", "title": "DHL Global Mail(5-9 workdays)", "price": 3.59},
        {"way": "DHLI", "title": "DHL Express(3-6 workdays)", "price": state["express_price"]}],
    "FR": lambda: [
        {"way": "LAPOSTE", "title": "La Poste(4-8 workdays)", "price": 4.82}],       # standard-only market
    "AU": lambda: [
        {"way": "AUPOST", "title": "Australia Post(6-10 workdays)", "price": 4.71},
        {"way": "DHLI", "title": "DHL Express(4-8 workdays)", "price": state["express_price"]}],
    "CA": lambda: [
        {"way": "CAPOST", "title": "Canada Post(5-10 workdays)", "price": 5.08},
        {"way": "DHLI", "title": "DHL Express(4-8 workdays)", "price": state["express_price"]}],
}


def fake_rates(country_id, postcode, city, products):
    time.sleep(state["delay"])
    pc = (postcode or "").replace(" ", "").upper()
    if pc.startswith("00") or pc.startswith("ZZ"):
        return []
    return RATES[country_id]()


txn.default_rate_fetcher = fake_rates
import app.routes.payments as payments  # noqa: E402

payments._live_stock_check_many = lambda pairs: (
    "'Sold out ring' just sold out — sorry! Please remove it to continue."
    if any(p.id == 4 for p, _ in pairs) else None)

import app.routes.intl_checkout as intl_checkout  # noqa: E402
from app.routes.intl_checkout import router as intl_router  # noqa: E402

# Fulfillment is TEST-DOUBLED: the real order pipeline (Silverbene, emails, Meta CAPI) never runs.
fulfilment_calls = []
payments.process_order_background = lambda data: fulfilment_calls.append(
    {"at": datetime.utcnow().isoformat(), "metadata": {k: v for k, v in data["metadata"].items()
                                                       if k in ("checkout_id", "stripe_session_id", "is_guest")}})
# Success redirects stay local so no live storefront / Meta pixel sees a sandbox purchase.
intl_checkout.GUEST_SUCCESS_URL = f"http://127.0.0.1:{os.getenv('HARNESS_PORT', '8123')}/"

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(intl_router)
app.include_router(payments.router)


@app.on_event("startup")
def seed():
    SQLModel.metadata.create_all(db.engine)
    with Session(db.engine) as s:
        ring_variants = [
            {"option_id": "R6", "attribute": [{"name": "Size", "value": "6"}], "qty": 9, "price": 40},
            {"option_id": "R7", "attribute": [{"name": "Size", "value": "7"}], "qty": 9, "price": 40}]
        rows = [
            (1, "Solitaire Ring", 298.0, "R6", ring_variants),
            (2, "Pearl Necklace", 248.0, "N1", None),
            (3, "Tennis Bracelet", 348.0, "B1", None),
            (4, "Sold out ring", 198.0, "S1", None)]
        for pid, name, price, sku, variants in rows:
            s.add(Product(id=pid, name=name, brand="Mikisi", description="qa", original_price=price,
                          final_price=price, silverbene_cost=40.0, cj_sku=sku, stock=5, is_active=True,
                          is_published=True, category="Rings", variants=json.dumps(variants) if variants else None))
        s.commit()


@app.get("/__harness/expire/{cid}")
def expire(cid: str):
    with Session(db.engine) as s:
        tx = s.get(CheckoutTransaction, cid)
        tx.quote_expires_at = datetime.utcnow() - timedelta(minutes=1)
        s.add(tx)
        s.commit()
    return {"expired": cid}


@app.get("/__harness/reprice")
def reprice(express: float):
    state["express_price"] = express
    return state


@app.get("/__harness/delay")
def delay(seconds: float):
    state["delay"] = seconds
    return state


@app.get("/__harness/tx/{cid}")
def tx_dump(cid: str):
    with Session(db.engine) as s:
        tx = s.get(CheckoutTransaction, cid)
        return tx.model_dump(mode="json") if tx else {}


@app.get("/__harness/paypal-mock")
def paypal_mock(code: str = ""):
    """Sandbox negative testing: code=INSTRUMENT_DECLINED (etc.) makes captures fail; empty clears it."""
    if code:
        os.environ["PAYPAL_SANDBOX_MOCK"] = code
    else:
        os.environ.pop("PAYPAL_SANDBOX_MOCK", None)
    return {"PAYPAL_SANDBOX_MOCK": os.environ.get("PAYPAL_SANDBOX_MOCK")}


@app.get("/__harness/checkouts")
def checkouts():
    with Session(db.engine) as s:
        from sqlmodel import select
        rows = s.exec(select(CheckoutTransaction).order_by(CheckoutTransaction.created_at.desc())).all()
        return [{"id": t.id[:8], "status": t.status, "provider": t.payment_provider, "attempts": t.payment_attempts,
                 "ref": t.payment_ref, "capture": t.payment_capture_id} for t in rows[:5]]


@app.get("/__harness/fulfilment")
def fulfilment():
    return {"test_double_calls": fulfilment_calls, "note": "Silverbene/email/Meta are never invoked in the harness"}


@app.get("/__harness/refund/{cid}")
def refund(cid: str, amount: float = None):
    with Session(db.engine) as s:
        body = intl_checkout.refund_checkout(s, cid, amount)
        tx = s.get(CheckoutTransaction, cid)
        return {"refund": {k: body.get(k) for k in ("id", "status")}, "tx_status": tx.status}


@app.get("/", response_class=HTMLResponse)
def index():
    html = open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8").read()
    return html.replace('const API = "https://api-project-production-d424.up.railway.app";',
                        f'const API = "http://127.0.0.1:{PORT}";')


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8123)
    PORT = ap.parse_args().port
    assert PORT == int(os.getenv("HARNESS_PORT", "8123")), "set HARNESS_PORT to match --port"
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
