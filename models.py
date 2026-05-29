from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from backend.database import Base


def now():
    return func.now()


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    supabase_user_id = Column(String(128), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    phone = Column(String(64), nullable=True)
    avatar_url = Column(String(1024), nullable=True)
    role = Column(String(32), nullable=False, default="customer")
    auth_provider = Column(String(64), nullable=True, default="supabase")
    last_login = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    carts = relationship("Cart", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    reserve_vaults = relationship("ReserveVault", back_populates="user", cascade="all, delete-orphan")
    reserve_positions = relationship("ReservePosition", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    admin_record = relationship("AdminUser", back_populates="user", uselist=False)
    memberships = relationship("UserMembership", back_populates="user", cascade="all, delete-orphan")
    referral_codes = relationship("ReferralCode", back_populates="user", cascade="all, delete-orphan")
    referral_usages = relationship("ReferralUsage", foreign_keys="ReferralUsage.referrer_id", back_populates="referrer", cascade="all, delete-orphan")
    referred_users = relationship("ReferralUsage", foreign_keys="ReferralUsage.referee_id", back_populates="referee", cascade="all, delete-orphan")
    referral_wallet = relationship("ReferralWallet", back_populates="user", uselist=False, cascade="all, delete-orphan")
    wallet = relationship("Wallet", back_populates="user", uselist=False, cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user", cascade="all, delete-orphan")


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    user_profile_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    is_superadmin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=now())

    user = relationship("UserProfile", back_populates="admin_record")
    sessions = relationship("AdminSession", back_populates="admin_user", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=False, default=0)
    slug = Column(String(255), nullable=True, unique=True, index=True)
    category = Column(String(128), nullable=True)
    image = Column(String(1024), nullable=True)
    stock_quantity = Column(Integer, nullable=False, default=0)
    inflation_savings = Column(Numeric(10, 2), nullable=True, default=0)
    storage_type = Column(String(64), nullable=True, default="pantry")
    reserve_lock_price = Column(Numeric(10, 2), nullable=True)
    locked_price = Column(Numeric(10, 2), nullable=True)
    lock_duration_days = Column(Integer, default=100)
    feeds_people = Column(Integer, nullable=False, default=4)
    reserve_days = Column(Integer, nullable=False, default=30)
    rating = Column(Numeric(3, 1), nullable=True, default=4.7)
    delivery_options = Column(String(255), nullable=True)
    metadata_json = Column("metadata", JSON, default={})
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")
    inventory = relationship("Inventory", back_populates="product", uselist=False, cascade="all, delete-orphan")
    cart_items = relationship("CartItem", back_populates="product")
    order_items = relationship("OrderItem", back_populates="product")
    reserve_items = relationship("ReserveItem", back_populates="product")
    reserve_positions = relationship("ReservePosition", back_populates="product")
    product_prices = relationship("ProductPrice", back_populates="product", cascade="all, delete-orphan")
    vault_market_prices = relationship("VaultMarketPrice", back_populates="product", cascade="all, delete-orphan")


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(1024), nullable=False)
    is_primary = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)

    product = relationship("Product", back_populates="images")


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, default=0, nullable=False)
    reserved_quantity = Column(Integer, default=0, nullable=False)
    incoming_quantity = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    product = relationship("Product", back_populates="inventory")


class Cart(Base):
    __tablename__ = "carts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    user = relationship("UserProfile", back_populates="carts")
    items = relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")


class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True, index=True)
    cart_id = Column(Integer, ForeignKey("carts.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    quantity = Column(Integer, default=1, nullable=False)
    price_snapshot = Column(Numeric(10, 2), nullable=False, default=0)
    reserve_option = Column(String(32), nullable=False, default="purchase")
    partial_delivery = Column(Boolean, default=False)
    lock_duration_days = Column(Integer, default=100)
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    cart = relationship("Cart", back_populates="items")
    product = relationship("Product", back_populates="cart_items")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    order_type = Column(String(32), nullable=False, default="purchase")
    total_amount = Column(Numeric(12, 2), nullable=False, default=0)
    payment_status = Column(String(32), nullable=False, default="pending")
    delivery_date = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    user = relationship("UserProfile", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False, default=0)
    total_price = Column(Numeric(12, 2), nullable=False, default=0)
    reserve_type = Column(String(32), nullable=False, default="purchase")
    partial_delivery = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=now())

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=0)
    currency = Column(String(16), nullable=False, default="USD")
    status = Column(String(32), nullable=False, default="confirmed")
    payment_method = Column(String(64), nullable=False, default="supabase-google")
    transaction_ref = Column(String(255), nullable=True)
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())

    order = relationship("Order", back_populates="payments")


class ReserveVault(Base):
    __tablename__ = "reserve_vaults"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="active")
    total_value = Column(Numeric(12, 2), nullable=False, default=0)
    upfront_paid = Column(Numeric(12, 2), nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    next_delivery_date = Column(DateTime(timezone=True), nullable=True)
    health_score = Column(Integer, default=100)
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    user = relationship("UserProfile", back_populates="reserve_vaults")
    reserve_items = relationship("ReserveItem", back_populates="reserve_vault", cascade="all, delete-orphan")
    reserve_positions = relationship("ReservePosition", back_populates="reserve_vault", cascade="all, delete-orphan")


class ReservePosition(Base):
    __tablename__ = "reserve_positions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    reserve_vault_id = Column(Integer, ForeignKey("reserve_vaults.id", ondelete="SET NULL"), nullable=True)
    reserved_quantity = Column(Integer, nullable=False, default=1)
    locked_price = Column(Numeric(12, 2), nullable=False, default=0)
    total_value = Column(Numeric(12, 2), nullable=False, default=0)
    deposit_paid = Column(Numeric(12, 2), nullable=False, default=0)
    ownership_percent = Column(Integer, nullable=False, default=0)
    remaining_balance = Column(Numeric(12, 2), nullable=False, default=0)
    lock_expires_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(32), nullable=False, default="active_lock")
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    user = relationship("UserProfile", back_populates="reserve_positions")
    product = relationship("Product", back_populates="reserve_positions")
    reserve_vault = relationship("ReserveVault", back_populates="reserve_positions")


class ReserveItem(Base):
    __tablename__ = "reserve_items"

    id = Column(Integer, primary_key=True, index=True)
    reserve_vault_id = Column(Integer, ForeignKey("reserve_vaults.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False, default=0)
    deposit_paid = Column(Numeric(12, 2), nullable=False, default=0)
    reserve_type = Column(String(32), nullable=False, default="deposit")
    partial_delivery = Column(Boolean, default=False)
    delivery_split = Column(JSON, default={})
    metadata_json = Column("metadata", JSON, default={})
    status = Column(String(32), nullable=False, default="locked")
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    reserve_vault = relationship("ReserveVault", back_populates="reserve_items")
    product = relationship("Product", back_populates="reserve_items")
    schedules = relationship("DeliverySchedule", back_populates="reserve_item", cascade="all, delete-orphan")


class DeliverySchedule(Base):
    __tablename__ = "delivery_schedules"

    id = Column(Integer, primary_key=True, index=True)
    reserve_item_id = Column(Integer, ForeignKey("reserve_items.id", ondelete="CASCADE"), nullable=False)
    scheduled_date = Column(DateTime(timezone=True), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="scheduled")
    notes = Column(Text, nullable=True)

    reserve_item = relationship("ReserveItem", back_populates="schedules")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(64), nullable=False, default="system")
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=now())

    user = relationship("UserProfile", back_populates="notifications")


class MembershipPlan(Base):
    __tablename__ = "membership_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    code = Column(String(64), unique=True, nullable=False)
    price = Column(Numeric(12, 2), nullable=False, default=0)
    billing_period = Column(String(32), nullable=False, default="year")
    status = Column(String(32), nullable=False, default="active")
    benefits_json = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    memberships = relationship("UserMembership", back_populates="plan")
    transactions = relationship("MembershipTransaction", back_populates="plan")


class UserMembership(Base):
    __tablename__ = "user_memberships"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(Integer, ForeignKey("membership_plans.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    effective_start = Column(DateTime(timezone=True), nullable=False)
    effective_end = Column(DateTime(timezone=True), nullable=False)
    auto_renew = Column(Boolean, default=True)
    renewal_count = Column(Integer, default=0)
    last_renewed_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    user = relationship("UserProfile", back_populates="memberships")
    plan = relationship("MembershipPlan", back_populates="memberships")
    transactions = relationship("MembershipTransaction", back_populates="membership", cascade="all, delete-orphan")
    benefits = relationship("MembershipBenefit", back_populates="membership", cascade="all, delete-orphan")


class MembershipTransaction(Base):
    __tablename__ = "membership_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    membership_id = Column(Integer, ForeignKey("user_memberships.id", ondelete="CASCADE"), nullable=True)
    plan_id = Column(Integer, ForeignKey("membership_plans.id", ondelete="CASCADE"), nullable=False)
    transaction_type = Column(String(64), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=0)
    currency = Column(String(8), nullable=False, default="USD")
    status = Column(String(32), nullable=False, default="confirmed")
    payment_method = Column(String(64), nullable=False, default="wallet")
    reference_id = Column(String(255), unique=True, nullable=False)
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())

    user = relationship("UserProfile")
    membership = relationship("UserMembership", back_populates="transactions")
    plan = relationship("MembershipPlan", back_populates="transactions")


class MembershipBenefit(Base):
    __tablename__ = "membership_benefits"

    id = Column(Integer, primary_key=True, index=True)
    membership_id = Column(Integer, ForeignKey("user_memberships.id", ondelete="CASCADE"), nullable=False)
    benefit_key = Column(String(128), nullable=False)
    benefit_value = Column(String(255), nullable=False)
    enabled = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)
    active_from = Column(DateTime(timezone=True), nullable=True)
    active_to = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=now())

    membership = relationship("UserMembership", back_populates="benefits")


class ReferralCode(Base):
    __tablename__ = "referral_codes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), unique=True, nullable=False)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    user = relationship("UserProfile", back_populates="referral_codes")
    usages = relationship("ReferralUsage", back_populates="referral_code", cascade="all, delete-orphan")


class ReferralUsage(Base):
    __tablename__ = "referral_usages"

    id = Column(Integer, primary_key=True, index=True)
    referral_code_id = Column(Integer, ForeignKey("referral_codes.id", ondelete="CASCADE"), nullable=False)
    referrer_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    referee_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="active")
    ip_hash = Column(String(255), nullable=True)
    used_at = Column(DateTime(timezone=True), server_default=now())
    metadata_json = Column("metadata", JSON, default={})

    referral_code = relationship("ReferralCode", back_populates="usages")
    referrer = relationship("UserProfile", foreign_keys=[referrer_id], back_populates="referral_usages")
    referee = relationship("UserProfile", foreign_keys=[referee_id], back_populates="referred_users")
    commissions = relationship("ReferralCommission", back_populates="usage", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("referee_id", name="uq_referral_usage_referee"),)


class ReferralCommission(Base):
    __tablename__ = "referral_commissions"

    id = Column(Integer, primary_key=True, index=True)
    usage_id = Column(Integer, ForeignKey("referral_usages.id", ondelete="CASCADE"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    amount = Column(Numeric(12, 2), nullable=False, default=0)
    eligible_amount = Column(Numeric(12, 2), nullable=False, default=0)
    status = Column(String(32), nullable=False, default="pending")
    approval_notes = Column(Text, nullable=True)
    wallet_transaction_id = Column(Integer, ForeignKey("wallet_transactions.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    usage = relationship("ReferralUsage", back_populates="commissions")
    order = relationship("Order")


class ReferralWallet(Base):
    __tablename__ = "referral_wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    current_balance = Column(Numeric(12, 2), nullable=False, default=0)
    total_earned = Column(Numeric(12, 2), nullable=False, default=0)
    total_paid = Column(Numeric(12, 2), nullable=False, default=0)
    last_updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    user = relationship("UserProfile", back_populates="referral_wallet")


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    balance = Column(Numeric(12, 2), nullable=False, default=0)
    currency = Column(String(8), nullable=False, default="USD")
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    user = relationship("UserProfile", back_populates="wallet")
    transactions = relationship("WalletTransaction", back_populates="wallet", cascade="all, delete-orphan")
    ledger_entries = relationship("LedgerEntry", back_populates="wallet", cascade="all, delete-orphan")


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id = Column(Integer, primary_key=True, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False)
    transaction_type = Column(String(64), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=0)
    currency = Column(String(8), nullable=False, default="USD")
    status = Column(String(32), nullable=False, default="posted")
    idempotency_key = Column(String(255), unique=True, nullable=False)
    reference_id = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    source_type = Column(String(64), nullable=False, default="manual")
    source_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=now())
    posted_at = Column(DateTime(timezone=True), nullable=True)

    wallet = relationship("Wallet", back_populates="transactions")
    ledger_entries = relationship("LedgerEntry", back_populates="transaction", cascade="all, delete-orphan")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False)
    transaction_id = Column(Integer, ForeignKey("wallet_transactions.id", ondelete="CASCADE"), nullable=False)
    account_type = Column(String(64), nullable=False)
    direction = Column(String(16), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=0)
    balance_after = Column(Numeric(12, 2), nullable=False, default=0)
    memo = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=now())

    wallet = relationship("Wallet", back_populates="ledger_entries")
    transaction = relationship("WalletTransaction", back_populates="ledger_entries")


class ProductPrice(Base):
    __tablename__ = "product_prices"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    currency = Column(String(8), nullable=False, default="USD")
    price = Column(Numeric(12, 2), nullable=False, default=0)
    country_code = Column(String(8), nullable=True)
    tier_name = Column(String(64), nullable=True)
    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    active = Column(Boolean, default=True)
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())

    product = relationship("Product", back_populates="product_prices")


class CurrencyRate(Base):
    __tablename__ = "currency_rates"

    id = Column(Integer, primary_key=True, index=True)
    currency = Column(String(8), nullable=False)
    rate_to_usd = Column(Numeric(12, 6), nullable=False)
    source = Column(String(64), nullable=False, default="manual")
    effective_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())


class PricingRule(Base):
    __tablename__ = "pricing_rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_type = Column(String(64), nullable=False)
    country_code = Column(String(8), nullable=True)
    currency = Column(String(8), nullable=True)
    membership_tier = Column(String(32), nullable=True)
    priority = Column(Integer, default=100)
    discount_percent = Column(Numeric(5, 2), nullable=True)
    reserve_lock_multiplier = Column(Numeric(5, 2), nullable=True)
    time_window_start = Column(String(16), nullable=True)
    time_window_end = Column(String(16), nullable=True)
    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())


class ReserveSellRule(Base):
    __tablename__ = "reserve_sell_rules"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    reserve_vault_id = Column(Integer, ForeignKey("reserve_vaults.id", ondelete="CASCADE"), nullable=False)
    reserve_item_id = Column(Integer, ForeignKey("reserve_items.id", ondelete="CASCADE"), nullable=False)
    auto_sell_enabled = Column(Boolean, default=True)
    threshold_percent = Column(Numeric(5, 2), nullable=False, default=5)
    min_profit_amount = Column(Numeric(12, 2), nullable=False, default=0)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())


class VaultMarketPrice(Base):
    __tablename__ = "vault_market_prices"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    market_price = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(8), nullable=False, default="USD")
    source = Column(String(64), nullable=False, default="manual")
    effective_at = Column(DateTime(timezone=True), server_default=now())
    created_at = Column(DateTime(timezone=True), server_default=now())

    product = relationship("Product", back_populates="vault_market_prices")


class AutoSellLog(Base):
    __tablename__ = "auto_sell_logs"

    id = Column(Integer, primary_key=True, index=True)
    reserve_item_id = Column(Integer, ForeignKey("reserve_items.id", ondelete="CASCADE"), nullable=False)
    rule_id = Column(Integer, ForeignKey("reserve_sell_rules.id", ondelete="CASCADE"), nullable=False)
    trigger_price = Column(Numeric(12, 2), nullable=False)
    current_price = Column(Numeric(12, 2), nullable=False)
    quantity_sold = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())


class ProfitDistribution(Base):
    __tablename__ = "profit_distribution"

    id = Column(Integer, primary_key=True, index=True)
    reserve_item_id = Column(Integer, ForeignKey("reserve_items.id", ondelete="CASCADE"), nullable=False)
    auto_sell_log_id = Column(Integer, ForeignKey("auto_sell_logs.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    wallet_transaction_id = Column(Integer, ForeignKey("wallet_transactions.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    actor_role = Column(String(32), nullable=True)
    action = Column(String(128), nullable=False)
    resource_type = Column(String(128), nullable=False)
    resource_id = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())

    user = relationship("UserProfile", back_populates="audit_logs")


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id = Column(Integer, primary_key=True, index=True)
    admin_user_id = Column(Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), nullable=False, unique=True)
    jti = Column(String(128), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, default=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=now())

    admin_user = relationship("AdminUser", back_populates="sessions")


class ReserveAnalytics(Base):
    __tablename__ = "reserve_analytics"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    metrics = Column(JSON, default={})
    period_start = Column(DateTime(timezone=True), nullable=True)
    period_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=now())


class InventoryTracking(Base):
    __tablename__ = "inventory_tracking"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    reserved_quantity = Column(Integer, nullable=False, default=0)
    snapshot_at = Column(DateTime(timezone=True), server_default=now())


class ReserveActivityLog(Base):
    __tablename__ = "reserve_activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(128), nullable=False)
    resource = Column(String(128), nullable=True)
    details = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
