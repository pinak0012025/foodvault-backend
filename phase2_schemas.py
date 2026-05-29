from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MembershipPlanCreate(BaseModel):
    name: str
    code: str
    price: Decimal = Field(default=29.0)
    billing_period: str = "year"
    benefits: Dict[str, Any] = Field(default_factory=dict)


class MembershipPlanOut(BaseModel):
    id: int
    name: str
    code: str
    price: float
    billing_period: str
    status: str
    benefits: Dict[str, Any]


class MembershipActivationRequest(BaseModel):
    plan_code: str
    auto_renew: bool = True


class UserMembershipOut(BaseModel):
    id: int
    user_id: int
    plan_id: int
    status: str
    effective_start: datetime
    effective_end: datetime
    auto_renew: bool
    renewal_count: int
    last_renewed_at: Optional[datetime]


class MembershipBenefitOut(BaseModel):
    id: int
    membership_id: int
    benefit_key: str
    benefit_value: str
    enabled: bool
    notes: Optional[str]


class MembershipTransactionOut(BaseModel):
    id: int
    user_id: int
    membership_id: Optional[int]
    plan_id: int
    transaction_type: str
    amount: float
    currency: str
    status: str
    payment_method: str
    reference_id: str
    created_at: datetime


class MembershipRenewalRequest(BaseModel):
    membership_id: int
    payment_method: str = "wallet"


class MembershipAnalyticsOut(BaseModel):
    total_memberships: int
    active_memberships: int
    expired_memberships: int
    premium_memberships: int
    monthly_renewals: int
    revenue: float


class ReferralCodeOut(BaseModel):
    id: int
    user_id: int
    code: str
    status: str


class ReferralUsageCreate(BaseModel):
    referral_code: str


class ReferralUsageOut(BaseModel):
    id: int
    referrer_id: int
    referee_id: int
    status: str
    used_at: datetime


class ReferralCommissionOut(BaseModel):
    id: int
    usage_id: int
    order_id: Optional[int]
    amount: float
    eligible_amount: float
    status: str
    approval_notes: Optional[str]


class ReferralAnalyticsOut(BaseModel):
    active_codes: int
    total_usages: int
    pending_commissions: int
    approved_commissions: int
    total_commission_value: float


class WalletOut(BaseModel):
    id: int
    user_id: int
    balance: float
    currency: str
    status: str


class WalletTransactionRequest(BaseModel):
    transaction_type: str
    amount: Decimal
    description: str
    idempotency_key: str
    source_type: str = "manual"
    source_id: Optional[str] = None


class WalletTransactionOut(BaseModel):
    id: int
    wallet_id: int
    transaction_type: str
    amount: float
    currency: str
    status: str
    idempotency_key: str
    reference_id: Optional[str]
    description: Optional[str]
    source_type: str
    source_id: Optional[str]
    created_at: datetime


class LedgerEntryOut(BaseModel):
    id: int
    wallet_id: int
    transaction_id: int
    account_type: str
    direction: str
    amount: float
    balance_after: float
    memo: Optional[str]
    created_at: datetime


class LocalizedPriceRequest(BaseModel):
    product_id: int
    currency: str = "USD"
    country_code: str = "US"
    quantity: int = 1
    reserve_type: str = "purchase"
    lock_days: int = 100


class LocalizedPriceResponse(BaseModel):
    product_id: int
    base_price: float
    final_price: float
    currency: str
    exchange_rate: float
    country_code: str
    reserve_type: str
    discount_applied: float
    pricing_snapshot: Dict[str, Any]


class ProductPriceUpsert(BaseModel):
    product_id: int
    currency: str
    price: Decimal
    country_code: Optional[str] = None
    tier_name: Optional[str] = None
    active: bool = True


class CurrencyRateUpsert(BaseModel):
    currency: str
    rate_to_usd: Decimal
    source: str = "manual"


class PricingRuleUpsert(BaseModel):
    rule_type: str
    country_code: Optional[str] = None
    currency: Optional[str] = None
    membership_tier: Optional[str] = None
    priority: int = 100
    discount_percent: Optional[Decimal] = None
    reserve_lock_multiplier: Optional[Decimal] = None
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None
    is_active: bool = True


class ReserveLockResponse(BaseModel):
    product_id: int
    reserve_price: float
    currency: str
    lock_days: int
    lock_until: datetime
    pricing_snapshot: Dict[str, Any]


class ReserveSellRuleUpsert(BaseModel):
    reserve_vault_id: int
    reserve_item_id: int
    auto_sell_enabled: bool = True
    threshold_percent: Decimal = 5
    min_profit_amount: Decimal = 0


class VaultMarketPriceUpsert(BaseModel):
    product_id: int
    market_price: Decimal
    currency: str = "USD"
    source: str = "manual"


class AutoSellLogOut(BaseModel):
    id: int
    reserve_item_id: int
    rule_id: int
    trigger_price: float
    current_price: float
    quantity_sold: int
    status: str
    created_at: datetime


class ProfitDistributionOut(BaseModel):
    id: int
    reserve_item_id: int
    auto_sell_log_id: int
    amount: float
    status: str


class VaultAnalyticsOut(BaseModel):
    rules: int
    market_prices: int
    auto_sells: int
    pending_profit_distributions: int
    total_profit_distributed: float


class JobRunResponse(BaseModel):
    job_name: str
    status: str
    summary: Dict[str, Any]


class AuditLogOut(BaseModel):
    id: int
    user_id: Optional[int]
    actor_role: Optional[str]
    action: str
    resource_type: str
    resource_id: Optional[str]
    message: str
    created_at: datetime
