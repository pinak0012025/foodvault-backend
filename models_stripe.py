from sqlalchemy import Column, String, Integer, Numeric, DateTime, ForeignKey, JSON, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from backend.database import Base
import uuid

def now():
    return func.now()

class StripeCustomer(Base):
    __tablename__ = "stripe_customers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    stripe_customer_id = Column(String(128), unique=True, nullable=False)
    email = Column(String(255), nullable=False)
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())
    user = relationship("UserProfile")

class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    stripe_payment_intent_id = Column(String(128), unique=True, nullable=False)
    status = Column(String(32), nullable=False)
    amount = Column(Numeric(12,2), nullable=False)
    currency = Column(String(8), nullable=False, default="USD")
    payment_method = Column(String(64), nullable=True)
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())
    payment = relationship("Payment")

class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    stripe_subscription_id = Column(String(128), unique=True, nullable=False)
    status = Column(String(32), nullable=False)
    plan_id = Column(Integer, ForeignKey("membership_plans.id", ondelete="SET NULL"), nullable=True)
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end = Column(Boolean, default=False)
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())
    user = relationship("UserProfile")
    plan = relationship("MembershipPlan")

class SubscriptionEvent(Base):
    __tablename__ = "subscription_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(64), nullable=False)
    event_id = Column(String(128), nullable=False)
    payload = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
    subscription = relationship("Subscription")

class StripeWebhookEvent(Base):
    __tablename__ = "stripe_webhook_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(String(128), unique=True, nullable=False)
    event_type = Column(String(64), nullable=False)
    payload = Column(JSON, default={})
    processed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=now())

class FinancialLedger(Base):
    __tablename__ = "financial_ledger"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id", ondelete="SET NULL"), nullable=True)
    transaction_id = Column(UUID(as_uuid=True), nullable=True)
    entry_type = Column(String(32), nullable=False)
    amount = Column(Numeric(12,2), nullable=False)
    currency = Column(String(8), nullable=False, default="USD")
    memo = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=now())

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    stripe_invoice_id = Column(String(128), unique=True, nullable=False)
    status = Column(String(32), nullable=False)
    amount_due = Column(Numeric(12,2), nullable=False)
    amount_paid = Column(Numeric(12,2), nullable=False)
    currency = Column(String(8), nullable=False, default="USD")
    due_date = Column(DateTime(timezone=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=now())
    updated_at = Column(DateTime(timezone=True), server_default=now(), onupdate=now())
