from sqlmodel import Session, select
from app.database import engine
from app.models.store_config import StoreConfig
from datetime import datetime


def get_config(key: str, default=None):
    """Get a store config value by key."""
    try:
        with Session(engine) as session:
            config = session.exec(
                select(StoreConfig).where(StoreConfig.key == key)
            ).first()
        if config:
            return float(config.value) if config.value.replace(".", "").isdigit() else config.value
        return default
    except Exception as e:
        print(f"[StoreConfig] Error getting {key}: {e}")
        return default


def set_config(key: str, value: str, description: str = ""):
    """Set or update a store config value."""
    try:
        with Session(engine) as session:
            existing = session.exec(
                select(StoreConfig).where(StoreConfig.key == key)
            ).first()
            if existing:
                existing.value = str(value)
                existing.updated_at = datetime.utcnow()
                session.add(existing)
            else:
                config = StoreConfig(
                    key=key,
                    value=str(value),
                    description=description,
                    updated_at=datetime.utcnow()
                )
                session.add(config)
            session.commit()
            print(f"[StoreConfig] ✅ {key} = {value}")
    except Exception as e:
        print(f"[StoreConfig] Error setting {key}: {e}")


def get_all_configs():
    """Get all store configs — for dashboard display."""
    with Session(engine) as session:
        return session.exec(select(StoreConfig)).all()