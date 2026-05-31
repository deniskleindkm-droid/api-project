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
from app.models.aria_operational import ARIAActionLedger, ARIATool, ARIAConversationState, ARIABusinessState, ARIAPolicy
from app.models.order import Order, OrderTracking
from app.models.content import ProductContent
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
        conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_verified boolean DEFAULT false'))
        conn.commit()

    _setup_defaults()


def _setup_defaults():
    _register_default_suppliers()
    _register_default_autonomy_rules()
    _register_default_configs()
    _register_default_tools()
    _register_default_policies()


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
    set_config("max_shipping_days", "30", "Maximum days before order is flagged as delayed")
    set_config("brand_voice", "Mikisi speaks to women who choose themselves. Every piece is an act of self-worth. Tone: elegant, empowering, intimate. Never corporate. Never pushy. Always making her feel seen.", "Mikisi brand voice for content generation")
    print("[DB] ✅ Default store configs registered")
    set_config("posting_schedule_instagram", "wednesday,thursday", "Best days to post on Instagram")
    set_config("posting_time_instagram", "21:00", "Best time to post on Instagram")
    set_config("posting_schedule_tiktok", "tuesday,wednesday,thursday,friday", "Best days to post on TikTok")
    set_config("posting_time_tiktok", "16:00", "Best time to post on TikTok")
    set_config("posting_schedule_pinterest", "tuesday,wednesday", "Best days to post on Pinterest")
    set_config("posting_time_pinterest", "11:00", "Best time to post on Pinterest")
    set_config("posting_schedule_facebook", "wednesday,thursday", "Best days to post on Facebook")
    set_config("posting_time_facebook", "19:00", "Best time to post on Facebook")
    set_config("auto_posting_enabled", "false", "Whether ARIA posts automatically — enable when credentials ready")
    set_config("locked_collection_ids", "13,14,15,16,17,18", "The only 6 allowed collections — agents cannot create or use others")
    set_config("collection_jewelry", "13", "Jewelry collection ID")
    set_config("collection_watches", "14", "Women Watches collection ID")
    set_config("collection_hair_accessories", "15", "Hair Accessories collection ID")
    set_config("collection_makeup", "16", "Makeup Accessories collection ID")
    set_config("collection_skincare", "17", "Skincare & Facial Tools collection ID")
    set_config("collection_nail_care", "18", "Nail Care collection ID")


def _register_default_tools():
    from app.models.aria_operational import ARIATool
    with Session(engine) as session:
        existing = session.exec(
            select(ARIATool).where(ARIATool.is_active == True)
        ).first()
        if existing:
            print("[DB] Tools already registered")
            return

        tools = [
            ARIATool(
                name="search_products",
                description="Search CJ Dropshipping for beauty products by keyword",
                agent="product_agent",
                adapter_key="cj.search_products",
                risk_level="low",
                requires_confirmation=False,
                verification_method="verify_search_returned_results",
            ),
            ARIATool(
                name="import_product",
                description="Import a product from CJ to Mikisi store by PID",
                agent="product_agent",
                adapter_key="cj.import_product_by_pid",
                risk_level="medium",
                requires_confirmation=False,
                verification_method="verify_product_exists_in_store",
                rollback_method="delete_product_draft",
            ),
            ARIATool(
                name="assign_collection",
                description="Assign a product to a collection",
                agent="store_agent",
                adapter_key="store.assign_collection",
                risk_level="low",
                requires_confirmation=False,
                verification_method="verify_collection_assigned",
                rollback_method="restore_previous_collection",
            ),
            ARIATool(
                name="update_product_price",
                description="Update the price of a product",
                agent="store_agent",
                adapter_key="store.update_price",
                risk_level="medium",
                requires_confirmation=True,
                verification_method="verify_price_updated",
                rollback_method="restore_previous_price",
            ),
            ARIATool(
                name="delete_product",
                description="Remove a product from the store",
                agent="store_agent",
                adapter_key="store.delete_product",
                risk_level="high",
                requires_confirmation=True,
                verification_method="verify_product_deleted",
                rollback_method="restore_deleted_product",
            ),
            ARIATool(
                name="send_email",
                description="Send an intelligence email to Dennis",
                agent="aria",
                adapter_key="email.send_to_dennis",
                risk_level="low",
                requires_confirmation=False,
                verification_method="verify_email_sent",
            ),
            ARIATool(
                name="score_product",
                description="Score a product for Mikisi fit using autonomy engine",
                agent="product_agent",
                adapter_key="scoring.score_product",
                risk_level="low",
                requires_confirmation=False,
                verification_method="verify_score_stored",
            ),
        ]

        for tool in tools:
            session.add(tool)
        session.commit()
        print("[DB] ✅ Default tools registered")


def _register_default_policies():
    from app.models.aria_operational import ARIAPolicy
    with Session(engine) as session:
        existing = session.exec(
            select(ARIAPolicy).where(ARIAPolicy.is_active == True)
        ).first()
        if existing:
            print("[DB] Policies already registered")
            return

        policies = [
            ARIAPolicy(
                action_type="search_products",
                risk_level="low",
                allowed_agents="product_agent,aria",
                requires_human_approval=False,
                requires_aria_approval=False,
                description="Searching is always safe"
            ),
            ARIAPolicy(
                action_type="import_product",
                risk_level="medium",
                allowed_agents="product_agent,aria",
                requires_human_approval=False,
                requires_aria_approval=False,
                description="Auto-import allowed if product score above threshold"
            ),
            ARIAPolicy(
                action_type="delete_product",
                risk_level="high",
                allowed_agents="aria",
                requires_human_approval=True,
                requires_aria_approval=True,
                rollback_required=True,
                description="Deleting products always requires Dennis approval"
            ),
            ARIAPolicy(
                action_type="update_price",
                risk_level="medium",
                allowed_agents="store_agent,aria",
                requires_human_approval=False,
                requires_aria_approval=True,
                rollback_required=True,
                description="Price changes need ARIA approval, rollback available"
            ),
            ARIAPolicy(
                action_type="post_social_media",
                risk_level="medium",
                allowed_agents="content_agent,posting_agent",
                requires_human_approval=False,
                requires_aria_approval=True,
                description="Social posts need ARIA approval before publishing"
            ),
            ARIAPolicy(
                action_type="send_mass_email",
                risk_level="high",
                allowed_agents="aria",
                requires_human_approval=True,
                requires_aria_approval=True,
                description="Mass emails always require Dennis approval"
            ),
            ARIAPolicy(
                action_type="deploy_code",
                risk_level="critical",
                allowed_agents="none",
                requires_human_approval=True,
                requires_aria_approval=True,
                rollback_required=True,
                description="Code deployment always requires Dennis — never autonomous"
            ),
        ]

        for policy in policies:
            session.add(policy)
        session.commit()
        print("[DB] ✅ Default policies registered")


def get_session():
    with Session(engine) as session:
        yield session