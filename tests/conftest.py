import os
import sys

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.pop("INTL_CHECKOUT", None)
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")

import app.database  # noqa: E402,F401  (registers every table on SQLModel.metadata)


@pytest.fixture()
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    for target in ("app.database.engine", "app.routes.payments.engine",
                   "app.checkout_intl.fulfillment.engine", "app.agents.store_config.engine"):
        monkeypatch.setattr(target, eng)
    return eng


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture()
def client(engine):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_session
    from app.routes.intl_checkout import router as intl_router
    from app.routes.payments import router as pay_router

    app = FastAPI()
    app.include_router(intl_router)
    app.include_router(pay_router)

    def _sess():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


@pytest.fixture()
def flag_on(monkeypatch):
    monkeypatch.setenv("INTL_CHECKOUT", "1")


def make_product(session, *, pid=1, name="Ring", price=298.0, cost=40.0, cj_sku="OPT1",
                 variants=None, stock=5):
    import json
    from app.models.product import Product
    p = Product(id=pid, name=name, brand="Mikisi", description="d", original_price=price, final_price=price,
                silverbene_cost=cost, cj_sku=cj_sku, stock=stock, is_active=True,
                is_published=True, category="Rings",
                variants=json.dumps(variants) if variants is not None else None)
    session.add(p)
    session.commit()
    return p


def quoted_tx(session, address, items, is_guest=True, fetcher=None):
    """Synchronous stand-in for the background quote: create_pending + run_quote."""
    from app.checkout_intl import transaction as txn
    tx = txn.create_pending(session, address=address, items=items, is_guest=is_guest)
    txn.run_quote(tx.id, fetcher)
    session.expire_all()
    return session.get(type(tx), tx.id)


def valid_address(country="US", **over):
    base = {
        "US": dict(line1="1 Main St", city="New York", admin_area="NY", postal_code="10001"),
        "CA": dict(line1="1 Rideau St", city="Ottawa", admin_area="ON", postal_code="K1A 0B1"),
        "GB": dict(line1="10 Downing St", city="London", admin_area="", postal_code="SW1A 2AA"),
        "DE": dict(line1="Unter den Linden 1", city="Berlin", admin_area="", postal_code="10117"),
        "FR": dict(line1="1 Rue de Rivoli", city="Paris", admin_area="", postal_code="75001"),
        "AU": dict(line1="1 George St", city="Sydney", admin_area="NSW", postal_code="2000"),
        "JP": dict(line1="1-1 Chiyoda", city="Tokyo", admin_area="Tokyo", postal_code="100-0001"),
        "NG": dict(line1="12 Marina Rd", city="Lagos", admin_area="Lagos", postal_code=""),
    }[country]
    d = dict(first_name="Ada", last_name="Lovelace", phone="+44 20 7946 0958",
             email="ada@example.com", country_code=country, **base)
    d.update(over)
    return d
