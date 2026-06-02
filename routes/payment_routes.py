from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import auth
from database import get_db
from models import MembershipPlan, MembershipTransaction, Product, UserMembership, UserProfile
from models_stripe import StripeCustomer, Subscription
from phase2_services import create_membership_benefits, ensure_seed_membership_plans
from stripe.payment_service import PaymentService

router = APIRouter()


class CreatePaymentIntentPayload:
    pass


def _normalize_product_id(product_id):
    try:
        return int(product_id)
    except (TypeError, ValueError):
        return None


def calculate_checkout_totals(payload: dict, product_lookup: dict) -> dict:
    items = payload.get("items") or []
    computed_purchase_total = Decimal("0.00")
    computed_reserve_upfront = Decimal("0.00")
    reserve_values = []

    for item in items:
        raw_product_id = item.get("product_id")
        normalized_product_id = _normalize_product_id(raw_product_id)
        quantity = max(int(item.get("quantity", 1)), 1)
        reserve_option = str(item.get("reserve_option", "purchase")).lower()
        action_type = str(item.get("action_type") or "LOCK").upper()

        product = product_lookup.get(normalized_product_id)
        if product is None:
            product = product_lookup.get(str(normalized_product_id))

        if not product:
            raise HTTPException(status_code=404, detail=f"Product {raw_product_id} not found")

        unit_price = Decimal(str(product.get("price") or 0))
        if reserve_option == "reserve":
            explicit_pay_now = item.get("pay_now")
            if explicit_pay_now is not None:
                reserve_line_total = Decimal(str(explicit_pay_now)).quantize(Decimal("0.01"))
            else:
                reserve_unit = product.get("locked_price")
                if reserve_unit in (None, ""):
                    reserve_unit = product.get("reserve_lock_price")
                if reserve_unit in (None, ""):
                    reserve_unit = unit_price
                reserve_line_total = (Decimal(str(reserve_unit)) * quantity).quantize(Decimal("0.01"))

            reserve_values.append({
                "product_id": normalized_product_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "name": product.get("name"),
                "action_type": action_type,
                "pay_now": reserve_line_total,
            })
            computed_reserve_upfront += reserve_line_total
        else:
            computed_purchase_total += unit_price * quantity

    explicit_reserve_upfront = payload.get("upfront_amount")
    if explicit_reserve_upfront is not None:
        computed_reserve_upfront = Decimal(str(explicit_reserve_upfront)).quantize(Decimal("0.01"))

    membership_fee = Decimal(str(payload.get("membership_fee", 0))).quantize(Decimal("0.01"))
    reserve_total_value = Decimal(str(payload.get("reserve_total_value", sum((item.get("pay_now") or 0) for item in items if str(item.get("reserve_option", "purchase")).lower() == "reserve")))).quantize(Decimal("0.01"))
    remaining_balance = Decimal(str(payload.get("remaining_balance", max(reserve_total_value - computed_reserve_upfront, Decimal("0.00"))))).quantize(Decimal("0.01"))
    expected_amount = (computed_purchase_total + computed_reserve_upfront + membership_fee).quantize(Decimal("0.01"))

    return {
        "purchase_total": computed_purchase_total.quantize(Decimal("0.01")),
        "reserve_upfront": computed_reserve_upfront.quantize(Decimal("0.01")),
        "reserve_total_value": reserve_total_value,
        "remaining_balance": remaining_balance,
        "membership_fee": membership_fee,
        "expected_amount": expected_amount,
        "reserve_values": reserve_values,
    }


@router.post("/api/stripe/create-payment-intent")
def create_payment_intent(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(auth.get_current_user),
):
    try:
        currency = str(payload.get("currency", "usd")).lower()
        items = payload.get("items") or []
        if not isinstance(items, list):
            raise HTTPException(status_code=400, detail="Checkout items must be provided as an array")

        product_lookup = {}
        product_ids = [item.get("product_id") for item in items]
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        for product in products:
            product_lookup[product.id] = {
                "price": product.price,
                "locked_price": product.locked_price,
                "reserve_lock_price": product.reserve_lock_price,
                "name": product.name,
            }
            product_lookup[str(product.id)] = product_lookup[product.id]

        totals = calculate_checkout_totals(payload, product_lookup)
        computed_purchase_total = totals["purchase_total"]
        computed_reserve_upfront = totals["reserve_upfront"]
        reserve_values = totals["reserve_values"]

        membership_selected = bool(payload.get("membership_selected"))
        membership_fee = totals["membership_fee"]
        membership_plan = None
        if membership_selected:
            ensure_seed_membership_plans(db)
            membership_plan = db.query(MembershipPlan).filter(MembershipPlan.code == "premium_year", MembershipPlan.status == "active").one_or_none()
            if not membership_plan:
                raise HTTPException(status_code=404, detail="Premium membership plan is not available")
            membership_fee = Decimal(str(membership_plan.price))

        expected_amount = (computed_purchase_total + computed_reserve_upfront + membership_fee).quantize(Decimal("0.01"))
        client_amount = Decimal(str(payload.get("amount", 0))).quantize(Decimal("0.01"))
        if client_amount != expected_amount:
            raise HTTPException(status_code=400, detail="Payment amount does not match the computed checkout total")

        if expected_amount <= 0:
            raise HTTPException(status_code=400, detail="Payment amount must be greater than zero")

        amount_cents = int(expected_amount * 100)
        customer = db.query(StripeCustomer).filter(StripeCustomer.user_id == current_user.id).one_or_none()
        if not customer:
            stripe_customer = PaymentService.create_customer(current_user.email, {
                "user_id": str(current_user.id),
                "supabase_user_id": current_user.supabase_user_id,
            })
            customer = StripeCustomer(
                user_id=current_user.id,
                stripe_customer_id=stripe_customer.id,
                email=current_user.email,
                metadata_json={"source": "checkout"},
            )
            db.add(customer)
            db.flush()

        intent = PaymentService.create_payment_intent(
            amount_cents=amount_cents,
            currency=currency,
            customer_id=customer.stripe_customer_id,
            metadata={
                "user_id": str(current_user.id),
                "email": current_user.email,
                "items": str(len(items)),
                "computed_purchase_total": str(computed_purchase_total.quantize(Decimal("0.01"))),
                "computed_reserve_upfront": str(computed_reserve_upfront.quantize(Decimal("0.01"))),
                "membership_enabled": str(membership_selected),
                "membership_fee": str(membership_fee.quantize(Decimal("0.01"))),
            },
            receipt_email=current_user.email,
        )

        if membership_selected:
            existing_membership = (
                db.query(UserMembership)
                .filter(UserMembership.user_id == current_user.id, UserMembership.status == "active")
                .order_by(UserMembership.effective_end.desc())
                .first()
            )
            if not existing_membership and membership_plan:
                effective_start = datetime.utcnow()
                effective_end = effective_start + timedelta(days=365)
                membership = UserMembership(
                    user_id=current_user.id,
                    plan_id=membership_plan.id,
                    status="pending",
                    effective_start=effective_start,
                    effective_end=effective_end,
                    auto_renew=True,
                    renewal_count=0,
                    metadata_json={
                        "source": "checkout",
                        "stripe_payment_intent_id": intent.id,
                    },
                )
                db.add(membership)
                db.flush()
                create_membership_benefits(db, membership, membership_plan)

                membership_transaction = MembershipTransaction(
                    user_id=current_user.id,
                    membership_id=membership.id,
                    plan_id=membership_plan.id,
                    transaction_type="purchase",
                    amount=membership_plan.price,
                    currency="USD",
                    status="pending",
                    payment_method="card",
                    reference_id=f"membership-checkout-{intent.id}",
                    metadata_json={
                        "stripe_payment_intent_id": intent.id,
                        "source": "checkout",
                    },
                )
                db.add(membership_transaction)

                subscription = Subscription(
                    user_id=current_user.id,
                    stripe_subscription_id=f"membership-checkout-{intent.id}",
                    status="pending",
                    plan_id=membership_plan.id,
                    current_period_start=effective_start,
                    current_period_end=effective_end,
                    cancel_at_period_end=False,
                    metadata_json={
                        "source": "checkout",
                        "stripe_payment_intent_id": intent.id,
                        "plan_code": membership_plan.code,
                    },
                )
                db.add(subscription)
                db.flush()
                membership.metadata_json = {
                    **(membership.metadata_json or {}),
                    "subscription_id": str(subscription.id),
                }
                db.commit()
            else:
                db.commit()

        return {
            "client_secret": intent.client_secret,
            "payment_intent_id": intent.id,
            "customer_id": customer.stripe_customer_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
