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
        conn.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS variants varchar(2000)"))
        conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_verified boolean DEFAULT false'))
        conn.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS material varchar(500)"))
        conn.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS sizes varchar(500)"))
        conn.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS colors varchar(500)"))
        conn.execute(text("ALTER TABLE cartitem ADD COLUMN IF NOT EXISTS selected_size varchar(100)"))
        conn.execute(text("ALTER TABLE cartitem ADD COLUMN IF NOT EXISTS selected_color varchar(100)"))
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
        # Silence CJ — disabled as primary supplier, Silverbene takes over
        cj = session.exec(select(Supplier).where(Supplier.name == "CJDropshipping")).first()
        if not cj:
            session.add(Supplier(
                name="CJDropshipping",
                adapter_class="app.agents.suppliers.cj_adapter.CJAdapter",
                base_url="https://developers.cjdropshipping.com/api2.0/v1",
                api_key_env="CJ_API_KEY",
                is_active=False,
                supported_categories="Beauty,Hair,Jewelry,Skincare,Makeup",
                supported_countries="US,CA,GB,AU,TZ,KE,ZA,NG,GH",
                reliability_score=1.0
            ))
            print("[DB] CJ Dropshipping registered but DISABLED — Silverbene is primary")
        elif cj.is_active:
            cj.is_active = False
            session.add(cj)
            print("[DB] ✅ CJ Dropshipping silenced — disabled for imports")

        # Register Silverbene as primary supplier
        sb = session.exec(select(Supplier).where(Supplier.name == "Silverbene")).first()
        if not sb:
            session.add(Supplier(
                name="Silverbene",
                adapter_class="app.agents.suppliers.silverbene_adapter.SilverbeneAdapter",
                base_url="https://s.silverbene.com",
                api_key_env="SILVERBENE_API_KEY",
                is_active=True,
                supported_categories="Rings,Necklaces,Bracelets,Earrings,Anklets,Ear Cuffs,Jewelry Sets",
                supported_countries="US,CA,GB,AU,TZ,KE,ZA,NG,GH",
                reliability_score=1.0
            ))
            print("[DB] ✅ Silverbene registered as primary supplier")
        else:
            print("[DB] Silverbene already registered")

        session.commit()


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


def _init_collection_id_slots(keys: list):
    """Insert collection ID config entries with value 0 only if they don't already exist."""
    from app.models.store_config import StoreConfig
    with Session(engine) as session:
        for key in keys:
            existing = session.exec(select(StoreConfig).where(StoreConfig.key == key)).first()
            if not existing:
                session.add(StoreConfig(key=key, value="0", description=f"{key} collection ID"))
        session.commit()


def _register_default_configs():
    from app.agents.store_config import set_config

    # ── Brand identity ─────────────────────────────────────────
    set_config("brand_voice", "Mikisi speaks to women who choose themselves. Every piece is an act of self-worth. Tone: elegant, empowering, intimate. Never corporate. Never pushy. Always making her feel seen.", "Mikisi brand voice")
    set_config("brand_type", "luxury_jewelry", "Mikisi is a luxury jewelry brand — not a beauty store")

    # ── Base pricing multipliers per collection ────────────────
    set_config("pricing_multiplier_rings", "8.0", "Base price multiplier for Rings")
    set_config("pricing_multiplier_necklaces", "7.0", "Base price multiplier for Necklaces")
    set_config("pricing_multiplier_bracelets", "7.0", "Base price multiplier for Bracelets")
    set_config("pricing_multiplier_earrings", "8.0", "Base price multiplier for Earrings")
    set_config("pricing_multiplier_anklets", "6.0", "Base price multiplier for Anklets")
    set_config("pricing_multiplier_ear_cuffs", "7.0", "Base price multiplier for Ear Cuffs")
    set_config("pricing_multiplier_jewelry_sets", "7.0", "Base price multiplier for Jewelry Sets")

    # ── Quality adjustments (applied on top of base) ───────────
    set_config("pricing_adj_moissanite", "2.5", "Quality adj for moissanite")
    set_config("pricing_adj_925_silver", "1.4", "Quality adj for 925 sterling silver")
    set_config("pricing_adj_natural_gemstone", "2.0", "Quality adj for natural gemstones")
    set_config("pricing_adj_pvd_plating", "1.2", "Quality adj for PVD plating")
    set_config("pricing_adj_18k_gold", "1.1", "Quality adj for 18k gold")
    set_config("pricing_adj_gold_plated", "1.0", "Quality adj for gold plated unspecified")
    set_config("pricing_adj_unknown_metal", "0.8", "Quality adj when metal is unknown")

    # ── Supplier adjustments ───────────────────────────────────
    set_config("pricing_supplier_silverbene", "1.3", "Supplier adj for Silverbene")
    set_config("pricing_supplier_nihaojewelry", "1.1", "Supplier adj for NihaoJewelry")
    set_config("pricing_supplier_cj", "1.0", "Supplier adj for CJ Dropshipping")

    # ── Price floor and ceilings ───────────────────────────────
    set_config("pricing_floor", "10.99", "Minimum price — never below this")
    set_config("pricing_ceiling_fashion", "80.00", "Max price for fashion tier")
    set_config("pricing_ceiling_premium", "150.00", "Max price for premium tier")
    set_config("pricing_ceiling_luxury", "500.00", "Max price for luxury tier")
    set_config("pricing_ceiling_ultra_luxury", "2000.00", "Max price for ultra luxury tier")

    # ── Shipping ───────────────────────────────────────────────
    set_config("shipping_target_country", "US", "Default shipping destination")
    set_config("shipping_max_days", "12", "Maximum acceptable shipping days")
    set_config("shipping_fallback_cost", "4.50", "Fallback shipping cost when API unavailable")
    # Shipping tiers — shown on every product panel
    set_config("shipping_express_label", "Express", "Express shipping display name")
    set_config("shipping_express_days", "5-8", "Express shipping days range eg. 5-8")
    set_config("shipping_express_carrier", "DHL Express", "Express carrier name")
    set_config("shipping_standard_label", "Standard", "Standard shipping display name")
    set_config("shipping_standard_days", "12-18", "Standard shipping days range eg. 12-18")
    set_config("shipping_standard_carrier", "ePacket / USPS", "Standard carrier name")
    set_config("shipping_economy_label", "Economy", "Economy shipping display name")
    set_config("shipping_economy_days", "20-35", "Economy shipping days range eg. 20-35")
    set_config("shipping_economy_carrier", "China Post", "Economy carrier name")
    set_config("shipping_free_threshold", "0", "Order value above which shipping is free (0=never)")

    # ── Packaging ─────────────────────────────────────────────
    set_config("packaging_cost_standard", "1.50", "Packaging cost for fashion/premium tier")
    set_config("packaging_cost_premium", "3.00", "Packaging cost for luxury/ultra-luxury tier")

    # Collection IDs are intentionally omitted here —
    # they are set exclusively by DELETE /agents/reset-store and must
    # not be overwritten on server restart.
    # Initialize new collection ID slots to 0 only if they don't exist yet.
    _init_collection_id_slots(["collection_ear_cuffs", "collection_jewelry_sets"])

    # ── Autonomy thresholds ────────────────────────────────────
    set_config("min_product_score", "0.65", "Minimum score for auto-import")
    set_config("max_products_per_trend", "3", "Max products to score per trend signal")
    set_config("auto_import_enabled", "true", "Whether ARIA auto-imports approved products")
    set_config("default_markup", "7.0", "Legacy fallback markup")

    # ── Social posting schedule ────────────────────────────────
    set_config("posting_schedule_instagram", "wednesday,thursday", "Best days to post on Instagram")
    set_config("posting_time_instagram", "21:00", "Best time to post on Instagram")
    set_config("posting_schedule_tiktok", "tuesday,wednesday,thursday,friday", "Best days to post on TikTok")
    set_config("posting_time_tiktok", "16:00", "Best time to post on TikTok")
    set_config("auto_posting_enabled", "false", "Whether ARIA posts automatically")

    print("[DB] ✅ Default store configs registered")


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