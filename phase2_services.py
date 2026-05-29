import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import (
    AuditLog,
    AutoSellLog,
    CurrencyRate,
    LedgerEntry,
    MembershipBenefit,
    MembershipPlan,
    MembershipTransaction,
    Order,
    PricingRule,
    Product,
    ProductPrice,
    ProfitDistribution,
    ReferralCode,
    ReferralCommission,
    ReferralUsage,
    ReferralWallet,
    ReserveItem,
    ReserveSellRule,
    ReserveVault,
    UserMembership,
    UserProfile,
    VaultMarketPrice,
    Wallet,
    WalletTransaction,
)
from backend.services import notify_user, to_serializable


def now_utc() -> datetime:
    return datetime.utcnow()


def safe_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def ensure_seed_membership_plans(db: Session) -> None:
    premium_plan = db.query(MembershipPlan).filter(MembershipPlan.code == "premium_year").one_or_none()
    if premium_plan:
        return

    plan = MembershipPlan(
        name="Premium",
        code="premium_year",
        price=Decimal("29.00"),
        billing_period="year",
        status="active",
        benefits_json={
            "product_discount": 40,
            "referral_earnings_enabled": True,
            "vault_profit_participation": True,
        },
    )
    db.add(plan)
    db.commit()


def get_or_create_wallet(db: Session, user: UserProfile) -> Wallet:
    wallet = db.query(Wallet).filter(Wallet.user_id == user.id).one_or_none()
    if wallet:
        return wallet
    wallet = Wallet(user_id=user.id, balance=Decimal("0.00"), currency="USD", status="active")
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    return wallet


def get_or_create_referral_wallet(db: Session, user: UserProfile) -> ReferralWallet:
    wallet = db.query(ReferralWallet).filter(ReferralWallet.user_id == user.id).one_or_none()
    if wallet:
        return wallet
    wallet = ReferralWallet(user_id=user.id, current_balance=Decimal("0.00"), total_earned=Decimal("0.00"), total_paid=Decimal("0.00"))
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    return wallet


def log_audit(db: Session, user: Optional[UserProfile], action: str, resource_type: str, resource_id: Optional[str], message: str, metadata: Optional[Dict[str, Any]] = None) -> AuditLog:
    audit = AuditLog(
        user_id=user.id if user else None,
        actor_role=user.role if user else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        message=message,
        metadata_json=metadata or {},
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def get_active_membership(db: Session, user: UserProfile) -> Optional[UserMembership]:
    return (
        db.query(UserMembership)
        .filter(UserMembership.user_id == user.id, UserMembership.status == "active")
        .order_by(UserMembership.effective_end.desc())
        .first()
    )


def get_membership_benefits(db: Session, membership: UserMembership) -> Dict[str, str]:
    benefits = db.query(MembershipBenefit).filter(MembershipBenefit.membership_id == membership.id).all()
    return {item.benefit_key: item.benefit_value for item in benefits}


def create_membership_benefits(db: Session, membership: UserMembership, plan: MembershipPlan) -> None:
    benefits_payload = plan.benefits_json or {}
    for key, value in benefits_payload.items():
        benefit = MembershipBenefit(
            membership_id=membership.id,
            benefit_key=key,
            benefit_value=str(value),
            enabled=True,
            notes=f"Auto-created from plan {plan.code}",
            active_from=membership.effective_start,
            active_to=membership.effective_end,
        )
        db.add(benefit)


def activate_membership(db: Session, user: UserProfile, plan_code: str, auto_renew: bool = True) -> UserMembership:
    ensure_seed_membership_plans(db)
    plan = db.query(MembershipPlan).filter(MembershipPlan.code == plan_code, MembershipPlan.status == "active").one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership plan not found")

    existing = get_active_membership(db, user)
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already has an active premium membership")

    wallet = get_or_create_wallet(db, user)
    apply_wallet_transaction(
        db,
        wallet,
        transaction_type="membership_purchase",
        amount=plan.price,
        description=f"Premium membership purchase: {plan.code}",
        idempotency_key=f"membership-purchase-{user.id}-{plan.code}",
        source_type="membership",
        source_id=str(plan.id),
        commit=False,
    )

    start = now_utc()
    end = start + timedelta(days=365)
    membership = UserMembership(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        effective_start=start,
        effective_end=end,
        auto_renew=auto_renew,
        renewal_count=0,
        metadata_json={"source": "manual"},
    )
    db.add(membership)
    db.flush()
    create_membership_benefits(db, membership, plan)
    transaction = MembershipTransaction(
        user_id=user.id,
        membership_id=membership.id,
        plan_id=plan.id,
        transaction_type="purchase",
        amount=plan.price,
        currency="USD",
        status="confirmed",
        payment_method="wallet",
        reference_id=f"membership-purchase-{user.id}-{membership.id}",
        metadata_json={"plan_code": plan.code},
    )
    db.add(transaction)
    db.commit()
    db.refresh(membership)
    return membership


def renew_membership(db: Session, membership: UserMembership, payment_method: str = "wallet") -> UserMembership:
    if membership.status not in {"active", "expired"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Membership cannot be renewed in its current state")

    plan = db.query(MembershipPlan).filter(MembershipPlan.id == membership.plan_id).one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership plan not found")

    user = db.query(UserProfile).filter(UserProfile.id == membership.user_id).one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    wallet = get_or_create_wallet(db, user)
    apply_wallet_transaction(
        db,
        wallet,
        transaction_type="membership_purchase",
        amount=plan.price,
        description=f"Membership renewal: {plan.code}",
        idempotency_key=f"membership-renewal-{membership.id}-{now_utc().timestamp()}",
        source_type="membership",
        source_id=str(plan.id),
        commit=False,
    )

    now = now_utc()
    new_end = now + timedelta(days=365)
    membership.status = "active"
    membership.effective_start = now
    membership.effective_end = new_end
    membership.auto_renew = True
    membership.renewal_count += 1
    membership.last_renewed_at = now

    transaction = MembershipTransaction(
        user_id=membership.user_id,
        membership_id=membership.id,
        plan_id=plan.id,
        transaction_type="renewal",
        amount=plan.price,
        currency="USD",
        status="confirmed",
        payment_method=payment_method,
        reference_id=f"membership-renewal-{membership.id}-{now.timestamp()}",
        metadata_json={"renewal_count": membership.renewal_count},
    )
    db.add(transaction)
    db.commit()
    db.refresh(membership)
    return membership


def deactivate_membership(db: Session, membership: UserMembership) -> UserMembership:
    membership.status = "cancelled"
    membership.auto_renew = False
    db.commit()
    db.refresh(membership)
    return membership


def expire_memberships(db: Session) -> Dict[str, int]:
    now = now_utc()
    memberships = db.query(UserMembership).filter(UserMembership.status == "active", UserMembership.effective_end <= now).all()
    expired = 0
    for membership in memberships:
        membership.status = "expired"
        membership.auto_renew = False
        expired += 1
    db.commit()
    return {"expired_memberships": expired}


def get_membership_analytics(db: Session) -> Dict[str, Any]:
    total_memberships = db.query(func.count(UserMembership.id)).scalar() or 0
    active_memberships = db.query(func.count(UserMembership.id)).filter(UserMembership.status == "active").scalar() or 0
    expired_memberships = db.query(func.count(UserMembership.id)).filter(UserMembership.status == "expired").scalar() or 0
    premium_memberships = db.query(func.count(UserMembership.id)).filter(UserMembership.plan_id == db.query(MembershipPlan.id).filter(MembershipPlan.code == "premium_year").scalar()).scalar() or 0
    monthly_renewals = db.query(func.count(MembershipTransaction.id)).filter(MembershipTransaction.transaction_type == "renewal", MembershipTransaction.created_at >= now_utc() - timedelta(days=30)).scalar() or 0
    revenue = db.query(func.coalesce(func.sum(MembershipTransaction.amount), 0)).filter(MembershipTransaction.status == "confirmed").scalar() or Decimal("0")
    return {
        "total_memberships": int(total_memberships),
        "active_memberships": int(active_memberships),
        "expired_memberships": int(expired_memberships),
        "premium_memberships": int(premium_memberships),
        "monthly_renewals": int(monthly_renewals),
        "revenue": float(revenue),
    }


def ensure_referral_code(db: Session, user: UserProfile) -> ReferralCode:
    existing = db.query(ReferralCode).filter(ReferralCode.user_id == user.id).one_or_none()
    if existing:
        return existing
    code = f"FV{user.id}{now_utc().strftime('%m%d%H%M%S')}"
    referral = ReferralCode(user_id=user.id, code=code.upper(), status="active")
    db.add(referral)
    db.commit()
    db.refresh(referral)
    return referral


def attach_referral_code(db: Session, user: UserProfile, referral_code: str) -> ReferralUsage:
    code = db.query(ReferralCode).filter(ReferralCode.code == referral_code.upper(), ReferralCode.status == "active").one_or_none()
    if not code:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Referral code not found")
    if code.user_id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Self-referrals are not allowed")

    existing = db.query(ReferralUsage).filter(ReferralUsage.referee_id == user.id).one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Referral already attached to this user")

    referrer = db.query(UserProfile).filter(UserProfile.id == code.user_id).one_or_none()
    if not referrer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Referrer not found")

    membership = get_active_membership(db, referrer)
    if not membership:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Referrer does not have an active premium membership")

    usage = ReferralUsage(referral_code_id=code.id, referrer_id=referrer.id, referee_id=user.id, status="active")
    db.add(usage)
    db.commit()
    db.refresh(usage)
    return usage


def create_referral_commission_for_order(db: Session, order: Order) -> Optional[ReferralCommission]:
    usage = db.query(ReferralUsage).filter(ReferralUsage.referee_id == order.user_id).order_by(ReferralUsage.used_at.desc()).first()
    if not usage:
        return None

    if order.total_amount < Decimal("500"):
        return None

    referrer = db.query(UserProfile).filter(UserProfile.id == usage.referrer_id).one_or_none()
    if not referrer or not get_active_membership(db, referrer):
        return None

    commission_amount = (order.total_amount * Decimal("0.10")).quantize(Decimal("0.01"))
    commission = ReferralCommission(
        usage_id=usage.id,
        order_id=order.id,
        amount=commission_amount,
        eligible_amount=order.total_amount,
        status="pending",
    )
    db.add(commission)
    db.commit()
    db.refresh(commission)
    return commission


def approve_referral_commission(db: Session, commission_id: int) -> ReferralCommission:
    commission = db.query(ReferralCommission).filter(ReferralCommission.id == commission_id).one_or_none()
    if not commission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Referral commission not found")
    if commission.status == "paid":
        return commission

    usage = db.query(ReferralUsage).filter(ReferralUsage.id == commission.usage_id).one_or_none()
    if not usage:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Referral usage not found")

    referrer = db.query(UserProfile).filter(UserProfile.id == usage.referrer_id).one_or_none()
    if not referrer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Referrer not found")

    wallet = get_or_create_wallet(db, referrer)
    tx = apply_wallet_transaction(
        db,
        wallet,
        transaction_type="referral_payout",
        amount=commission.amount,
        description=f"Referral payout for order {commission.order_id}",
        idempotency_key=f"referral-payout-{commission.id}",
        source_type="referral",
        source_id=str(commission.id),
        commit=False,
    )
    referral_wallet = get_or_create_referral_wallet(db, referrer)
    referral_wallet.current_balance += commission.amount
    referral_wallet.total_earned += commission.amount
    commission.status = "paid"
    commission.wallet_transaction_id = tx.id
    db.commit()
    db.refresh(commission)
    return commission


def get_referral_analytics(db: Session) -> Dict[str, Any]:
    active_codes = db.query(func.count(ReferralCode.id)).filter(ReferralCode.status == "active").scalar() or 0
    total_usages = db.query(func.count(ReferralUsage.id)).scalar() or 0
    pending_commissions = db.query(func.count(ReferralCommission.id)).filter(ReferralCommission.status == "pending").scalar() or 0
    approved_commissions = db.query(func.count(ReferralCommission.id)).filter(ReferralCommission.status == "approved").scalar() or 0
    total_commission_value = db.query(func.coalesce(func.sum(ReferralCommission.amount), 0)).filter(ReferralCommission.status == "paid").scalar() or Decimal("0")
    return {
        "active_codes": int(active_codes),
        "total_usages": int(total_usages),
        "pending_commissions": int(pending_commissions),
        "approved_commissions": int(approved_commissions),
        "total_commission_value": float(total_commission_value),
    }


def apply_wallet_transaction(
    db: Session,
    wallet: Wallet,
    transaction_type: str,
    amount: Decimal,
    description: str,
    idempotency_key: str,
    source_type: str = "manual",
    source_id: Optional[str] = None,
    commit: bool = True,
) -> WalletTransaction:
    existing = db.query(WalletTransaction).filter(WalletTransaction.idempotency_key == idempotency_key).one_or_none()
    if existing:
        return existing

    amount_decimal = safe_decimal(amount)
    if amount_decimal <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount must be positive")

    wallet_row = db.query(Wallet).filter(Wallet.id == wallet.id).with_for_update().one_or_none()
    if not wallet_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found")

    if transaction_type in {"debit", "membership_purchase", "hold"} and wallet_row.balance < amount_decimal:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient wallet balance")

    new_balance = wallet_row.balance
    if transaction_type in {"debit", "membership_purchase", "hold"}:
        new_balance -= amount_decimal
    else:
        new_balance += amount_decimal

    tx = WalletTransaction(
        wallet_id=wallet.id,
        transaction_type=transaction_type,
        amount=amount_decimal,
        currency=wallet.currency,
        status="posted",
        idempotency_key=idempotency_key,
        reference_id=f"wallet-{wallet.id}-{datetime.utcnow().timestamp()}",
        description=description,
        source_type=source_type,
        source_id=source_id,
        posted_at=now_utc(),
    )
    db.add(tx)
    db.flush()

    wallet_row.balance = new_balance
    db.add(wallet_row)

    if transaction_type in {"debit", "membership_purchase", "hold"}:
        ledger1 = LedgerEntry(wallet_id=wallet.id, transaction_id=tx.id, account_type="wallet", direction="debit", amount=amount_decimal, balance_after=new_balance, memo=description)
        ledger2 = LedgerEntry(wallet_id=wallet.id, transaction_id=tx.id, account_type="expense", direction="credit", amount=amount_decimal, balance_after=new_balance, memo=description)
    else:
        ledger1 = LedgerEntry(wallet_id=wallet.id, transaction_id=tx.id, account_type="wallet", direction="credit", amount=amount_decimal, balance_after=new_balance, memo=description)
        ledger2 = LedgerEntry(wallet_id=wallet.id, transaction_id=tx.id, account_type="equity", direction="debit", amount=amount_decimal, balance_after=new_balance, memo=description)

    db.add(ledger1)
    db.add(ledger2)
    if commit:
        db.commit()
    db.refresh(tx)
    return tx


def list_wallet_transactions(db: Session, user: UserProfile) -> List[WalletTransaction]:
    wallet = get_or_create_wallet(db, user)
    return db.query(WalletTransaction).filter(WalletTransaction.wallet_id == wallet.id).order_by(WalletTransaction.created_at.desc()).all()


def reconcile_wallet_balances(db: Session) -> Dict[str, int]:
    wallets = db.query(Wallet).all()
    updated = 0
    for wallet in wallets:
        entries = db.query(LedgerEntry).filter(LedgerEntry.wallet_id == wallet.id).all()
        calculated_balance = Decimal("0")
        for entry in entries:
            if entry.direction == "credit":
                calculated_balance += entry.amount
            else:
                calculated_balance -= entry.amount
        if wallet.balance != calculated_balance:
            wallet.balance = calculated_balance
            updated += 1
    db.commit()
    return {"reconciled": updated}


def upsert_product_price(db: Session, payload: Dict[str, Any]) -> ProductPrice:
    price = db.query(ProductPrice).filter(
        ProductPrice.product_id == payload["product_id"],
        ProductPrice.currency == payload["currency"],
        ProductPrice.country_code == payload.get("country_code"),
        ProductPrice.tier_name == payload.get("tier_name"),
    ).one_or_none()
    if not price:
        price = ProductPrice(**payload)
        db.add(price)
    else:
        for key, value in payload.items():
            setattr(price, key, value)
    db.commit()
    db.refresh(price)
    return price


def upsert_currency_rate(db: Session, payload: Dict[str, Any]) -> CurrencyRate:
    rate = db.query(CurrencyRate).filter(CurrencyRate.currency == payload["currency"]).one_or_none()
    if not rate:
        rate = CurrencyRate(**payload)
        db.add(rate)
    else:
        rate.rate_to_usd = payload["rate_to_usd"]
        rate.source = payload.get("source", rate.source)
    db.commit()
    db.refresh(rate)
    return rate


def upsert_pricing_rule(db: Session, payload: Dict[str, Any]) -> PricingRule:
    rule = PricingRule(**payload)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def get_localized_price(db: Session, product_id: int, currency: str, country_code: str, quantity: int, reserve_type: str, lock_days: int, active_membership: Optional[UserMembership] = None) -> Dict[str, Any]:
    product = db.query(Product).filter(Product.id == product_id, Product.is_active.is_(True)).one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    base_price = product.price
    product_price = db.query(ProductPrice).filter(ProductPrice.product_id == product_id, ProductPrice.currency == currency, ProductPrice.active.is_(True)).order_by(ProductPrice.updated_at.desc()).first()
    if product_price:
        base_price = product_price.price

    if reserve_type == "reserve" and product.reserve_lock_price is not None:
        base_price = product.reserve_lock_price

    currency_rate = db.query(CurrencyRate).filter(CurrencyRate.currency == currency).order_by(CurrencyRate.updated_at.desc()).first()
    exchange_rate = float(currency_rate.rate_to_usd) if currency_rate else 1.0
    if currency == "USD":
        exchange_rate = 1.0

    discount_applied = Decimal("0.00")
    if active_membership:
        plan = db.query(MembershipPlan).filter(MembershipPlan.id == active_membership.plan_id).one_or_none()
        if plan and plan.benefits_json:
            plan_discount = plan.benefits_json.get("product_discount")
            if isinstance(plan_discount, (int, float)):
                discount_applied = Decimal(str(plan_discount))

    pricing_snapshot = {"source": "product_price" if product_price else "product.base", "currency": currency, "country_code": country_code}

    rules = db.query(PricingRule).filter(PricingRule.is_active.is_(True)).all()
    for rule in sorted(rules, key=lambda item: item.priority):
        if rule.country_code and rule.country_code != country_code:
            continue
        if rule.currency and rule.currency != currency:
            continue
        if rule.membership_tier and (not active_membership or active_membership.status != "active"):
            continue
        if rule.membership_tier and active_membership:
            pass
        if rule.rule_type == "membership_discount" and active_membership:
            discount_applied = safe_decimal(rule.discount_percent or 0)
            pricing_snapshot["membership_discount"] = float(discount_applied)
        if rule.rule_type == "time_based" and rule.time_window_start and rule.time_window_end:
            current_hour = now_utc().hour
            start = int(rule.time_window_start)
            end = int(rule.time_window_end)
            if start <= current_hour <= end:
                pricing_snapshot["time_based_rule"] = rule.id
        if rule.rule_type == "reserve_lock" and reserve_type == "reserve" and rule.reserve_lock_multiplier:
            base_price = base_price * rule.reserve_lock_multiplier
            pricing_snapshot["reserve_lock_multiplier"] = float(rule.reserve_lock_multiplier)

    final_price = (base_price * (Decimal("1") - discount_applied / Decimal("100"))).quantize(Decimal("0.01"))
    if currency != "USD":
        final_price = (final_price * Decimal(str(exchange_rate))).quantize(Decimal("0.01"))
    return {
        "product_id": product.id,
        "base_price": float(base_price),
        "final_price": float(final_price),
        "currency": currency,
        "exchange_rate": float(exchange_rate),
        "country_code": country_code,
        "reserve_type": reserve_type,
        "discount_applied": float(discount_applied),
        "pricing_snapshot": pricing_snapshot,
    }


def create_reserve_lock(db: Session, product_id: int, currency: str, lock_days: int, country_code: str, user: UserProfile) -> Dict[str, Any]:
    price = get_localized_price(db, product_id, currency, country_code, 1, "reserve", lock_days, get_active_membership(db, user))
    lock_until = now_utc() + timedelta(days=lock_days)
    result = {**price, "lock_until": lock_until}
    return result


def upsert_vault_market_price(db: Session, payload: Dict[str, Any]) -> VaultMarketPrice:
    market = VaultMarketPrice(
        product_id=payload["product_id"],
        market_price=safe_decimal(payload["market_price"]),
        currency=payload.get("currency", "USD"),
        source=payload.get("source", "manual"),
    )
    db.add(market)
    db.commit()
    db.refresh(market)
    return market


def create_reserve_sell_rule(db: Session, rule_payload: Dict[str, Any]) -> ReserveSellRule:
    rule = ReserveSellRule(
        user_id=rule_payload["user_id"],
        reserve_vault_id=rule_payload["reserve_vault_id"],
        reserve_item_id=rule_payload["reserve_item_id"],
        auto_sell_enabled=rule_payload.get("auto_sell_enabled", True),
        threshold_percent=safe_decimal(rule_payload.get("threshold_percent", 5)),
        min_profit_amount=safe_decimal(rule_payload.get("min_profit_amount", 0)),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def evaluate_auto_sells(db: Session) -> Dict[str, Any]:
    rules = db.query(ReserveSellRule).filter(ReserveSellRule.status == "active").all()
    logs = 0
    distributed = Decimal("0")
    for rule in rules:
        reserve_item = db.query(ReserveItem).filter(ReserveItem.id == rule.reserve_item_id).one_or_none()
        if not reserve_item:
            continue
        if reserve_item.status == "sold":
            continue
        market_price = db.query(VaultMarketPrice).filter(VaultMarketPrice.product_id == reserve_item.product_id).order_by(VaultMarketPrice.created_at.desc()).first()
        current_price = market_price.market_price if market_price else reserve_item.unit_price
        trigger_price = (reserve_item.unit_price * (Decimal("1") + (rule.threshold_percent / Decimal("100")))).quantize(Decimal("0.01"))
        if current_price < trigger_price:
            continue

        profit = (current_price - reserve_item.unit_price) * reserve_item.quantity
        if profit < rule.min_profit_amount:
            continue

        sell_log = AutoSellLog(
            reserve_item_id=reserve_item.id,
            rule_id=rule.id,
            trigger_price=trigger_price,
            current_price=current_price,
            quantity_sold=reserve_item.quantity,
            status="completed",
        )
        db.add(sell_log)
        db.flush()

        reserve_item.status = "sold"
        product = reserve_item.product
        if product and product.inventory:
            product.inventory.quantity += reserve_item.quantity
            product.inventory.reserved_quantity = max(product.inventory.reserved_quantity - reserve_item.quantity, 0)

        wallet = db.query(Wallet).filter(Wallet.user_id == reserve_item.reserve_vault.user_id).one_or_none()
        if not wallet:
            wallet = get_or_create_wallet(db, reserve_item.reserve_vault.user)

        wallet_tx = apply_wallet_transaction(
            db,
            wallet,
            transaction_type="reserve_profit",
            amount=profit,
            description=f"Auto-sell profit for reserve item {reserve_item.id}",
            idempotency_key=f"auto-sell-profit-{reserve_item.id}-{sell_log.id}",
            source_type="auto_sell",
            source_id=str(sell_log.id),
        )

        distribution = ProfitDistribution(
            reserve_item_id=reserve_item.id,
            auto_sell_log_id=sell_log.id,
            amount=profit,
            wallet_transaction_id=wallet_tx.id,
            status="paid",
        )
        db.add(distribution)
        logs += 1
        distributed += profit
    db.commit()
    return {"auto_sells": logs, "profit_distributed": float(distributed)}


def get_vault_profit_analytics(db: Session) -> Dict[str, Any]:
    rules = db.query(ReserveSellRule).count()
    market_prices = db.query(VaultMarketPrice).count()
    auto_sells = db.query(AutoSellLog).count()
    pending_distributions = db.query(ProfitDistribution).filter(ProfitDistribution.status == "pending").count()
    total_profit = db.query(func.coalesce(func.sum(ProfitDistribution.amount), 0)).scalar() or Decimal("0")
    return {
        "rules": int(rules),
        "market_prices": int(market_prices),
        "auto_sells": int(auto_sells),
        "pending_profit_distributions": int(pending_distributions),
        "total_profit_distributed": float(total_profit),
    }


def run_membership_expiry_job(db: Session) -> Dict[str, Any]:
    return expire_memberships(db)


def run_referral_payout_job(db: Session) -> Dict[str, Any]:
    pending = db.query(ReferralCommission).filter(ReferralCommission.status == "pending").all()
    approved = 0
    for commission in pending:
        approve_referral_commission(db, commission.id)
        approved += 1
    return {"approved": approved}


def run_wallet_settlement_job(db: Session) -> Dict[str, Any]:
    return reconcile_wallet_balances(db)


def run_notification_dispatch_job(db: Session) -> Dict[str, Any]:
    pending_notifications = db.query(AuditLog).all()
    return {"notifications_processed": len(pending_notifications)}


def get_admin_audit_logs(db: Session) -> List[AuditLog]:
    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(100).all()
