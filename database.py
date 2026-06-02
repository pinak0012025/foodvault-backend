import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")
load_dotenv(dotenv_path=BASE_DIR.parent / ".env", override=False)

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL")

if not DATABASE_URL:
    DATABASE_URL = f"sqlite:///{BASE_DIR}/backend.db"

engine = create_engine(DATABASE_URL, future=True, echo=False)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def ensure_product_columns() -> None:
    with engine.begin() as conn:
        current_columns = {column["name"] for column in inspect(conn).get_columns("products")}
        if "vendor_id" not in current_columns:
            conn.execute(text("ALTER TABLE products ADD COLUMN vendor_id INTEGER"))
            current_columns.add("vendor_id")
        if "metadata" not in current_columns:
            conn.execute(text("ALTER TABLE products ADD COLUMN metadata JSON DEFAULT '{}'"))
            current_columns = {column["name"] for column in inspect(conn).get_columns("products")}

        column_definitions = {
            "slug": "VARCHAR(255)",
            "category": "VARCHAR(128)",
            "image": "VARCHAR(1024)",
            "stock_quantity": "INTEGER DEFAULT 0",
            "inflation_savings": "NUMERIC(10, 2) DEFAULT 0",
            "storage_type": "VARCHAR(64) DEFAULT 'pantry'",
            "locked_price": "NUMERIC(10, 2)",
            "feeds_people": "INTEGER DEFAULT 4",
            "reserve_days": "INTEGER DEFAULT 30",
            "rating": "NUMERIC(3, 1) DEFAULT 4.7",
        }

        for column_name, definition in column_definitions.items():
            if column_name not in current_columns:
                conn.execute(text(f"ALTER TABLE products ADD COLUMN {column_name} {definition}"))
                current_columns.add(column_name)


def ensure_procurement_tables() -> None:
    Base.metadata.create_all(bind=engine)


def ensure_user_profile_columns() -> None:
    with engine.begin() as conn:
        current_columns = {column["name"] for column in inspect(conn).get_columns("user_profiles")}
        if "auth_provider" not in current_columns:
            conn.execute(text("ALTER TABLE user_profiles ADD COLUMN auth_provider VARCHAR(64)"))
            current_columns.add("auth_provider")
        if "last_login" not in current_columns:
            conn.execute(text("ALTER TABLE user_profiles ADD COLUMN last_login DATETIME"))
            current_columns.add("last_login")
        if "metadata" not in current_columns:
            conn.execute(text("ALTER TABLE user_profiles ADD COLUMN metadata JSON DEFAULT '{}'"))
            current_columns.add("metadata")


def ensure_reserve_item_columns() -> None:
    with engine.begin() as conn:
        current_columns = {column["name"] for column in inspect(conn).get_columns("reserve_items")}
        if "metadata" not in current_columns:
            conn.execute(text("ALTER TABLE reserve_items ADD COLUMN metadata JSON DEFAULT '{}'"))


def seed_default_products() -> None:
    from models import Inventory, Product

    db = SessionLocal()
    try:
        if db.query(Product).count() > 0:
            return

        products = [
            Product(
                sku="FV-RICE-25KG",
                name="Premium Basmati Rice 25kg",
                description="High-quality long-grain rice for dependable pantry storage and everyday meals.",
                price=49.0,
                slug="premium-basmati-rice-25kg",
                category="Grains & Staples",
                image="/assets/images/no_image.png",
                stock_quantity=96,
                inflation_savings=22.0,
                storage_type="dry pantry",
                reserve_lock_price=39.0,
                locked_price=39.0,
                lock_duration_days=100,
                feeds_people=120,
                reserve_days=60,
                rating=4.8,
                delivery_options="standard",
                metadata_json={"category": "Grains & Staples", "source": "seed"},
                is_active=True,
            ),
            Product(
                sku="FV-OATS-10KG",
                name="Organic Rolled Oats 10kg",
                description="Whole-grain oats built for long-term nutrition and easy breakfast prep.",
                price=29.0,
                slug="organic-rolled-oats-10kg",
                category="Grains & Staples",
                image="/assets/images/no_image.png",
                stock_quantity=80,
                inflation_savings=16.0,
                storage_type="dry pantry",
                reserve_lock_price=25.0,
                locked_price=25.0,
                lock_duration_days=100,
                feeds_people=80,
                reserve_days=45,
                rating=4.7,
                delivery_options="standard",
                metadata_json={"category": "Grains & Staples", "source": "seed"},
                is_active=True,
            ),
            Product(
                sku="FV-MEAL-KIT-72",
                name="Emergency Meal Kit (72 meals)",
                description="Ready-to-eat calories for households that need immediate resilience.",
                price=129.0,
                slug="emergency-meal-kit-72",
                category="Ready Meals",
                image="/assets/images/no_image.png",
                stock_quantity=42,
                inflation_savings=31.0,
                storage_type="sheltered storage",
                reserve_lock_price=109.0,
                locked_price=109.0,
                lock_duration_days=100,
                feeds_people=72,
                reserve_days=90,
                rating=4.9,
                delivery_options="priority",
                metadata_json={"category": "Ready Meals", "source": "seed"},
                is_active=True,
            ),
            Product(
                sku="FV-FREEZE-VEG",
                name="Freeze-Dried Vegetables Pack",
                description="Lightweight, shelf-stable vegetables for quick meals and high nutrient density.",
                price=39.0,
                slug="freeze-dried-vegetables-pack",
                category="Freeze-Dried",
                image="/assets/images/no_image.png",
                stock_quantity=55,
                inflation_savings=18.0,
                storage_type="low humidity",
                reserve_lock_price=34.0,
                locked_price=34.0,
                lock_duration_days=100,
                feeds_people=30,
                reserve_days=120,
                rating=4.6,
                delivery_options="standard",
                metadata_json={"category": "Freeze-Dried", "source": "seed"},
                is_active=True,
            ),
            Product(
                sku="FV-BEANS-PACK",
                name="Canned Beans Variety Pack",
                description="A balanced canned protein pack with long shelf life and strong meal flexibility.",
                price=24.0,
                slug="canned-beans-variety-pack",
                category="Canned Goods",
                image="/assets/images/no_image.png",
                stock_quantity=66,
                inflation_savings=12.0,
                storage_type="ambient",
                reserve_lock_price=20.0,
                locked_price=20.0,
                lock_duration_days=100,
                feeds_people=20,
                reserve_days=90,
                rating=4.4,
                delivery_options="standard",
                metadata_json={"category": "Canned Goods", "source": "seed"},
                is_active=True,
            ),
            Product(
                sku="FV-KIT-FAMILY",
                name="Family Emergency Kit",
                description="A practical weekly reserve kit for families needing reliable preparedness.",
                price=184.0,
                slug="family-emergency-kit",
                category="Emergency Kits",
                image="/assets/images/no_image.png",
                stock_quantity=30,
                inflation_savings=38.0,
                storage_type="sheltered storage",
                reserve_lock_price=154.0,
                locked_price=154.0,
                lock_duration_days=100,
                feeds_people=5,
                reserve_days=30,
                rating=4.8,
                delivery_options="priority",
                metadata_json={"category": "Emergency Kits", "source": "seed"},
                is_active=True,
            ),
        ]

        db.add_all(products)
        db.flush()

        for product in products:
            db.add(Inventory(product=product, quantity=product.stock_quantity, reserved_quantity=0, incoming_quantity=0))

        db.commit()
    finally:
        db.close()


def init_db() -> None:
    import models  # noqa: F401
    import models_stripe  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_product_columns()
    ensure_user_profile_columns()
    ensure_reserve_item_columns()
    ensure_procurement_tables()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
