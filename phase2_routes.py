from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import auth
from database import get_db
from models import MembershipPlan, ReferralCommission, ReferralUsage, UserMembership, UserProfile
from phase2_schemas import (
    AuditLogOut,
    CurrencyRateUpsert,
    JobRunResponse,
    LocalizedPriceRequest,
    LocalizedPriceResponse,
    MembershipActivationRequest,
    MembershipAnalyticsOut,
    MembershipPlanOut,
    MembershipRenewalRequest,
    MembershipTransactionOut,
    ProductPriceUpsert,
    PricingRuleUpsert,
    ReferralAnalyticsOut,
    ReferralCodeOut,
    ReferralUsageCreate,
    ReferralUsageOut,
    ReserveLockResponse,
    ReserveSellRuleUpsert,
    VaultAnalyticsOut,
    VaultMarketPriceUpsert,
    WalletOut,
    WalletTransactionOut,
    WalletTransactionRequest,
)
from phase2_services import (
    activate_membership,
    apply_wallet_transaction,
    approve_referral_commission,
    attach_referral_code,
    create_reserve_lock,
    create_reserve_sell_rule,
    deactivate_membership,
    ensure_referral_code,
    ensure_seed_membership_plans,
    evaluate_auto_sells,
    get_active_membership,
    get_admin_audit_logs,
    get_localized_price,
    get_membership_analytics,
    get_or_create_wallet,
    get_referral_analytics,
    get_vault_profit_analytics,
    list_wallet_transactions,
    log_audit,
    renew_membership,
    reconcile_wallet_balances,
    run_membership_expiry_job,
    run_notification_dispatch_job,
    run_referral_payout_job,
    run_wallet_settlement_job,
    upsert_currency_rate,
    upsert_product_price,
    upsert_pricing_rule,
    upsert_vault_market_price,
)

router = APIRouter(prefix="/api/phase2", tags=["phase2"])


def require_active_membership(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user)) -> UserMembership:
    membership = get_active_membership(db, current_user)
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active premium membership required")
    return membership


@router.get("/memberships/plans", response_model=list[MembershipPlanOut])
def list_membership_plans(db: Session = Depends(get_db)):
    ensure_seed_membership_plans(db)
    plans = db.query(MembershipPlan).order_by(MembershipPlan.name).all()
    return [
        MembershipPlanOut(
            id=plan.id,
            name=plan.name,
            code=plan.code,
            price=float(plan.price),
            billing_period=plan.billing_period,
            status=plan.status,
            benefits=plan.benefits_json or {},
        )
        for plan in plans
    ]


@router.post("/memberships/activate", response_model=Dict[str, Any])
def activate_membership_route(payload: MembershipActivationRequest, db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user)):
    membership = activate_membership(db, current_user, payload.plan_code, payload.auto_renew)
    return {"membership_id": membership.id, "status": membership.status}


@router.get("/memberships", response_model=list[MembershipTransactionOut])
def list_memberships(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user)):
    memberships = db.query(UserMembership).filter(UserMembership.user_id == current_user.id).order_by(UserMembership.created_at.desc()).all()
    return [
        MembershipTransactionOut(
            id=membership.id,
            user_id=membership.user_id,
            membership_id=membership.id,
            plan_id=membership.plan_id,
            transaction_type="membership",
            amount=float(db.query(MembershipPlan.price).filter(MembershipPlan.id == membership.plan_id).scalar() or 0),
            currency="USD",
            status=membership.status,
            payment_method="wallet",
            reference_id=f"membership-{membership.id}",
            created_at=membership.created_at,
        )
        for membership in memberships
    ]


@router.post("/memberships/{membership_id}/renew", response_model=Dict[str, Any])
def renew_membership_route(membership_id: int, payload: MembershipRenewalRequest, db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user)):
    membership = db.query(UserMembership).filter(UserMembership.id == membership_id, UserMembership.user_id == current_user.id).one_or_none()
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found")
    renew_membership(db, membership, payment_method=payload.payment_method)
    return {"membership_id": membership.id, "status": "renewed"}


@router.post("/memberships/{membership_id}/deactivate", response_model=Dict[str, Any])
def deactivate_membership_route(membership_id: int, db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user)):
    membership = db.query(UserMembership).filter(UserMembership.id == membership_id, UserMembership.user_id == current_user.id).one_or_none()
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found")
    deactivate_membership(db, membership)
    return {"membership_id": membership.id, "status": "deactivated"}


@router.get("/memberships/analytics", response_model=MembershipAnalyticsOut)
def membership_analytics_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    analytics = get_membership_analytics(db)
    return MembershipAnalyticsOut(**analytics)


@router.post("/referrals/codes", response_model=ReferralCodeOut)
def create_referral_code_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user), membership: UserMembership = Depends(require_active_membership)):
    code = ensure_referral_code(db, current_user)
    return ReferralCodeOut(id=code.id, user_id=code.user_id, code=code.code, status=code.status)


@router.post("/referrals/attach", response_model=ReferralUsageOut)
def attach_referral_route(payload: ReferralUsageCreate, db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user)):
    usage = attach_referral_code(db, current_user, payload.referral_code)
    return ReferralUsageOut(id=usage.id, referrer_id=usage.referrer_id, referee_id=usage.referee_id, status=usage.status, used_at=usage.used_at)


@router.get("/referrals/history", response_model=list[ReferralUsageOut])
def referral_history_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user)):
    usages = db.query(ReferralUsage).filter((ReferralUsage.referrer_id == current_user.id) | (ReferralUsage.referee_id == current_user.id)).order_by(ReferralUsage.used_at.desc()).all()
    return [ReferralUsageOut(id=usage.id, referrer_id=usage.referrer_id, referee_id=usage.referee_id, status=usage.status, used_at=usage.used_at) for usage in usages]


@router.get("/referrals/commissions", response_model=list[Dict[str, Any]])
def referral_commissions_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user)):
    commissions = db.query(ReferralCommission).join(ReferralUsage).filter(ReferralUsage.referrer_id == current_user.id).order_by(ReferralCommission.created_at.desc()).all()
    return [{"id": commission.id, "amount": float(commission.amount), "status": commission.status, "order_id": commission.order_id} for commission in commissions]


@router.get("/referrals/analytics", response_model=ReferralAnalyticsOut)
def referral_analytics_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    analytics = get_referral_analytics(db)
    return ReferralAnalyticsOut(**analytics)


@router.post("/referrals/commissions/{commission_id}/approve", response_model=Dict[str, Any])
def approve_commission_route(commission_id: int, db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    commission = approve_referral_commission(db, commission_id)
    log_audit(db, current_user, "approve_referral_commission", "ReferralCommission", str(commission.id), "Approved referral commission")
    return {"commission_id": commission.id, "status": commission.status}


@router.get("/wallets", response_model=WalletOut)
def get_wallet_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user)):
    wallet = get_or_create_wallet(db, current_user)
    return WalletOut(id=wallet.id, user_id=wallet.user_id, balance=float(wallet.balance), currency=wallet.currency, status=wallet.status)


@router.get("/wallets/transactions", response_model=list[WalletTransactionOut])
def wallet_transactions_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user)):
    transactions = list_wallet_transactions(db, current_user)
    return [
        WalletTransactionOut(
            id=item.id,
            wallet_id=item.wallet_id,
            transaction_type=item.transaction_type,
            amount=float(item.amount),
            currency=item.currency,
            status=item.status,
            idempotency_key=item.idempotency_key,
            reference_id=item.reference_id,
            description=item.description,
            source_type=item.source_type,
            source_id=item.source_id,
            created_at=item.created_at,
        )
        for item in transactions
    ]


@router.post("/wallets/transactions", response_model=WalletTransactionOut)
def wallet_transaction_route(payload: WalletTransactionRequest, db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user)):
    wallet = get_or_create_wallet(db, current_user)
    tx = apply_wallet_transaction(
        db,
        wallet,
        transaction_type=payload.transaction_type,
        amount=payload.amount,
        description=payload.description,
        idempotency_key=payload.idempotency_key,
        source_type=payload.source_type,
        source_id=payload.source_id,
    )
    return WalletTransactionOut(
        id=tx.id,
        wallet_id=tx.wallet_id,
        transaction_type=tx.transaction_type,
        amount=float(tx.amount),
        currency=tx.currency,
        status=tx.status,
        idempotency_key=tx.idempotency_key,
        reference_id=tx.reference_id,
        description=tx.description,
        source_type=tx.source_type,
        source_id=tx.source_id,
        created_at=tx.created_at,
    )


@router.post("/wallets/reconcile", response_model=Dict[str, Any])
def wallet_reconcile_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    result = reconcile_wallet_balances(db)
    log_audit(db, current_user, "reconcile_wallet_balances", "Wallet", "wallets", "Reconciled wallet balances")
    return result


@router.get("/pricing/localized", response_model=LocalizedPriceResponse)
def localized_price_route(
    product_id: int,
    currency: str = "USD",
    country_code: str = "US",
    quantity: int = 1,
    reserve_type: str = "purchase",
    lock_days: int = 100,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(auth.get_current_user),
):
    active_membership = get_active_membership(db, current_user)
    price = get_localized_price(db, product_id, currency, country_code, quantity, reserve_type, lock_days, active_membership)
    return LocalizedPriceResponse(
        product_id=price["product_id"],
        base_price=price["base_price"],
        final_price=price["final_price"],
        currency=price["currency"],
        exchange_rate=price["exchange_rate"],
        country_code=price["country_code"],
        reserve_type=price["reserve_type"],
        discount_applied=price["discount_applied"],
        pricing_snapshot=price["pricing_snapshot"],
    )


@router.post("/pricing/product-prices", response_model=Dict[str, Any])
def upsert_product_price_route(payload: ProductPriceUpsert, db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    price = upsert_product_price(db, payload.model_dump())
    log_audit(db, current_user, "upsert_product_price", "ProductPrice", str(price.id), "Updated product price")
    return {"id": price.id, "status": "saved"}


@router.post("/pricing/currency-rates", response_model=Dict[str, Any])
def upsert_currency_rate_route(payload: CurrencyRateUpsert, db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    rate = upsert_currency_rate(db, payload.model_dump())
    log_audit(db, current_user, "upsert_currency_rate", "CurrencyRate", str(rate.id), "Updated currency rate")
    return {"id": rate.id, "status": "saved"}


@router.post("/pricing/rules", response_model=Dict[str, Any])
def upsert_pricing_rule_route(payload: PricingRuleUpsert, db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    rule = upsert_pricing_rule(db, payload.model_dump())
    log_audit(db, current_user, "upsert_pricing_rule", "PricingRule", str(rule.id), "Updated pricing rule")
    return {"id": rule.id, "status": "saved"}


@router.post("/pricing/lock", response_model=ReserveLockResponse)
def reserve_lock_route(payload: LocalizedPriceRequest, db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.get_current_user)):
    result = create_reserve_lock(db, payload.product_id, payload.currency, payload.lock_days, payload.country_code, current_user)
    return ReserveLockResponse(
        product_id=result["product_id"],
        reserve_price=result["final_price"],
        currency=result["currency"],
        lock_days=payload.lock_days,
        lock_until=result["lock_until"],
        pricing_snapshot=result["pricing_snapshot"],
    )


@router.post("/vaults/market-prices", response_model=Dict[str, Any])
def vault_market_price_route(payload: VaultMarketPriceUpsert, db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    market = upsert_vault_market_price(db, payload.model_dump())
    log_audit(db, current_user, "upsert_vault_market_price", "VaultMarketPrice", str(market.id), "Updated vault market price")
    return {"id": market.id, "status": "saved"}


@router.post("/vaults/rules", response_model=Dict[str, Any])
def reserve_sell_rule_route(payload: ReserveSellRuleUpsert, db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    rule = create_reserve_sell_rule(db, payload.model_dump() | {"user_id": current_user.id})
    log_audit(db, current_user, "create_reserve_sell_rule", "ReserveSellRule", str(rule.id), "Created reserve sell rule")
    return {"id": rule.id, "status": "saved"}


@router.post("/vaults/evaluate", response_model=JobRunResponse)
def vault_evaluate_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    result = evaluate_auto_sells(db)
    log_audit(db, current_user, "evaluate_auto_sells", "AutoSellLog", str(result["auto_sells"]), "Evaluated auto-sell rules")
    return JobRunResponse(job_name="vault_profit_evaluation", status="completed", summary=result)


@router.get("/vaults/analytics", response_model=VaultAnalyticsOut)
def vault_analytics_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    analytics = get_vault_profit_analytics(db)
    return VaultAnalyticsOut(**analytics)


@router.post("/jobs/membership-expiry", response_model=JobRunResponse)
def membership_expiry_job_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    result = run_membership_expiry_job(db)
    return JobRunResponse(job_name="membership_expiry", status="completed", summary=result)


@router.post("/jobs/referral-payout", response_model=JobRunResponse)
def referral_payout_job_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    result = run_referral_payout_job(db)
    return JobRunResponse(job_name="referral_payout", status="completed", summary=result)


@router.post("/jobs/wallet-settlement", response_model=JobRunResponse)
def wallet_settlement_job_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    result = run_wallet_settlement_job(db)
    return JobRunResponse(job_name="wallet_settlement", status="completed", summary=result)


@router.post("/jobs/dispatch-notifications", response_model=JobRunResponse)
def dispatch_notifications_job_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    result = run_notification_dispatch_job(db)
    return JobRunResponse(job_name="dispatch_notifications", status="completed", summary=result)


@router.get("/audit-logs", response_model=list[AuditLogOut])
def audit_logs_route(db: Session = Depends(get_db), current_user: UserProfile = Depends(auth.require_admin_user)):
    logs = get_admin_audit_logs(db)
    return [
        AuditLogOut(
            id=log.id,
            user_id=log.user_id,
            actor_role=log.actor_role,
            action=log.action,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            message=log.message,
            created_at=log.created_at,
        )
        for log in logs
    ]
