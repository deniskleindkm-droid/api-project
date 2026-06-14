"""
DB Cleanup Agent
----------------
Hard-deletes products that no longer belong in the system.

Rule:
  - Non-Silverbene products with is_active=False are truly gone —
    they were soft-deleted (the DELETE /products route sets is_active=False).
    Hard-delete them so they stop polluting the database.

  - Silverbene products with is_active=False are OUT OF STOCK, not deleted.
    The stock agent manages them and will set is_active=True when stock returns.
    Never hard-delete Silverbene products.

Runs on startup and daily at 03:00 UTC.
"""
from sqlmodel import Session, select
from app.database import engine
from app.models.product import Product


def run_db_cleanup():
    with Session(engine) as session:
        # Find all soft-deleted non-Silverbene products
        dead = session.exec(
            select(Product).where(
                Product.is_active == False,
                (Product.supplier_name != "Silverbene") | (Product.supplier_name == None)
            )
        ).all()

        if not dead:
            print("[DB Cleanup] No dead products found — database is clean")
            return

        ids = [p.id for p in dead]
        names = [p.name[:40] for p in dead[:5]]
        print(f"[DB Cleanup] Hard-deleting {len(dead)} dead non-Silverbene products")
        print(f"[DB Cleanup] Examples: {names}{'...' if len(dead) > 5 else ''}")

        for p in dead:
            session.delete(p)
        session.commit()

        print(f"[DB Cleanup] Done — removed {len(dead)} rows (IDs: {ids[:10]}{'...' if len(ids) > 10 else ''})")
