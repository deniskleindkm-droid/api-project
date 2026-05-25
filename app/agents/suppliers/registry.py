import importlib
from sqlmodel import Session, select
from app.database import engine
from app.models.supplier import Supplier


def get_supplier(name: str = "CJDropshipping"):
    """
    Load and return the adapter for a named supplier.
    Usage: supplier = get_supplier("CJDropshipping")
    """
    with Session(engine) as session:
        supplier = session.exec(
            select(Supplier).where(
                Supplier.name == name,
                Supplier.is_active == True
            )
        ).first()

    if not supplier:
        print(f"[Registry] Supplier not found: {name}")
        return None

    try:
        module_path, class_name = supplier.adapter_class.rsplit(".", 1)
        module = importlib.import_module(module_path)
        adapter_class = getattr(module, class_name)
        return adapter_class()
    except Exception as e:
        print(f"[Registry] Failed to load adapter for {name}: {e}")
        return None


def get_all_active_suppliers():
    """
    Return all active supplier adapters.
    Used for searching across multiple suppliers.
    """
    with Session(engine) as session:
        suppliers = session.exec(
            select(Supplier).where(Supplier.is_active == True)
        ).all()

    adapters = []
    for supplier in suppliers:
        try:
            module_path, class_name = supplier.adapter_class.rsplit(".", 1)
            module = importlib.import_module(module_path)
            adapter_class = getattr(module, class_name)
            adapters.append({
                "name": supplier.name,
                "adapter": adapter_class()
            })
        except Exception as e:
            print(f"[Registry] Failed to load {supplier.name}: {e}")

    return adapters