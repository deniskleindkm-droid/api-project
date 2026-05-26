from sqlmodel import SQLModel, Session, create_engine, select
from app.models.user import User
from app.models.product import Product
from app.models.order import Order
from app.models.cart import CartItem
from app.models.agent import AgentMemory, AgentTask, MarketInsight, MonthlyVision, AgentLearning, AgentGoal
from app.models.signal import SystemSignal
from app.models.supplier import Supplier
from app.models.collection import Collection
from app.models.autonomy import AutonomyRule, ProductScore
from app.models.store_config import StoreConfig
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./users.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)


def create_db():
    SQLModel.metadata.create_all(engine)

    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE product ALTER COLUMN cj_sku TYPE varchar(200)"))
        conn.execute(text("ALTER TABLE product ALTER COLUMN cj_product_id TYPE varchar(200)"))
        conn.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS images varchar(2000)"))
        conn.commit()

    _setup_defaults()


def _setup_defaults():
    _register_default_suppliers()
    _register_default_autonomy_rules()
    _register_default_configs()


def _register_default_suppliers():
    with Session(engine) as session:
        existing = session.exec(
            select(Supplier).where(Supplier.name == "CJDropshipping")
        ).first()
        if not existing:
            cj = Supplier(
                name="CJDropshipping",
                adapter_class="app.agents.suppliers.cj_adapter.CJAdapter",
                base_url="https://developers.cjdropshipping.com/api2.0/v1",
                api_key_env="CJ_API_KEY",
                is_active=True,
                supported_categories="Beauty,Hair,Jewelry,Skincare,Makeup",
                supported_countries="US,CA,GB,AU,TZ,KE,ZA,NG,GH",
                reliability_score=1.0
            )
            session.add(cj)
            session.commit()
            print("[DB] ✅ CJ Dropshipping registered as supplier")
        else:
            print("[DB] CJ Dropshipping already registered")


def _register_default_autonomy_rules():
    with Session(engine) as session:
        existing = session.exec(
            select(AutonomyRule).where(AutonomyRule.is_active == True)
        ).first()
        if existing:
            print("[DB] Autonomy rules already registered")
            return

        rules = [
            AutonomyRule(
                agent="product_agent",
                action="import_product",
                condition_field="total_score",
                condition_operator="gte",
                condition_value=0.65,
                autonomous=True,
                description="Auto-import products scoring 0.65 or above"
            ),
            AutonomyRule(
                agent="product_agent",
                action="import_product",
                condition_field="total_score",
                condition_operator="lt",
                condition_value=0.65,
                autonomous=False,
                signal_to="aria",
                priority=5,
                description="Signal ARIA for products scoring below 0.65"
            ),
            AutonomyRule(
                agent="order_agent",
                action="handle_failure",
                condition_field="retry_count",
                condition_operator="lt",
                condition_value=3,
                autonomous=True,
                description="Auto-retry failed orders up to 3 times"
            ),
            AutonomyRule(
                agent="order_agent",
                action="handle_failure",
                condition_field="retry_count",
                condition_operator="gte",
                condition_value=3,
                autonomous=False,
                signal_to="dennis",
                priority=1,
                description="Signal Dennis when order fails 3+ times"
            ),
            AutonomyRule(
                agent="inventory_agent",
                action="flag_stock",
                condition_field="stock_level",
                condition_operator="lt",
                condition_value=10,
                autonomous=False,
                signal_to="aria",
                priority=3,
                description="Signal ARIA when stock below 10"
            ),
            AutonomyRule(
                agent="content_agent",
                action="post_content",
                condition_field="content_score",
                condition_operator="gte",
                condition_value=0.70,
                autonomous=True,
                description="Auto-post content scoring 0.70 or above"
            ),
            AutonomyRule(
                agent="content_agent",
                action="post_content",
                condition_field="content_score",
                condition_operator="lt",
                condition_value=0.70,
                autonomous=False,
                signal_to="aria",
                priority=5,
                description="Signal ARIA for low-scoring content"
            ),
        ]

        for rule in rules:
            session.add(rule)
        session.commit()
        print("[DB] ✅ Default autonomy rules registered")


def _register_default_configs():
    from app.agents.store_config import set_config
    set_config("default_markup", "7.0", "Default price markup multiplier for all products")
    set_config("min_product_score", "0.65", "Minimum score for auto-import")
    set_config("max_products_per_trend", "3", "Max products to score per trend signal")
    set_config("auto_import_enabled", "true", "Whether ARIA auto-imports approved products")
    print("[DB] ✅ Default store configs registered")


def get_session():
    with Session(engine) as session:
        yield session