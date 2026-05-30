import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

import services
from config import settings
from database import get_db
from models import AuditLog, Payment, UserProfile
from models_stripe import FinancialLedger, Invoice, PaymentTransaction, StripeCustomer, StripeWebhookEvent, Subscription, SubscriptionEvent
from stripe.webhook_service import WebhookService

router = APIRouter()
logger = logging.getLogger(__name__)


def get_user_by_stripe_customer(db: Session, stripe_customer_id: str | None):
    if not stripe_customer_id:
        return None
    customer = db.query(StripeCustomer).filter(StripeCustomer.stripe_customer_id == stripe_customer_id).one_or_none()
    if not customer:
        return None
    return db.query(UserProfile).filter(UserProfile.id == customer.user_id).one_or_none()


def serialize_stripe_value(value):
    if hasattr(value, "to_dict"):
        return serialize_stripe_value(value.to_dict())
    if isinstance(value, dict):
        return {str(key): serialize_stripe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_stripe_value(item) for item in value]
    return value


@router.post("/api/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    event = WebhookService.verify_signature(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    if not event:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    logger.info("Received Stripe webhook event %s (%s)", event.id, event.type)

    existing = db.query(StripeWebhookEvent).filter(StripeWebhookEvent.event_id == event.id).one_or_none()
    if existing:
        logger.info("Stripe webhook event %s already processed", event.id)
        return {"status": "already_processed"}

    stored_event = StripeWebhookEvent(
        event_id=event.id,
        event_type=event.type,
        payload=serialize_stripe_value(event.to_dict()),
        processed=False,
    )
    db.add(stored_event)
    db.commit()

    event_data = serialize_stripe_value(event.data.get("object", {}))
    user = get_user_by_stripe_customer(db, str(event_data.get("customer")) if event_data.get("customer") else None)

    if event.type in {"invoice.paid", "invoice.payment_failed", "customer.subscription.created", "customer.subscription.updated"} and not user:
        db.add(
            AuditLog(
                user_id=None,
                actor_role="system",
                action="stripe_event_missing_customer",
                resource_type="stripe_event",
                resource_id=event.id,
                message=f"Stripe event {event.id} could not be matched to a user profile",
                metadata_json={"event_type": event.type},
            )
        )
        stored_event.processed = True
        db.commit()
        return {"status": "ignored_missing_customer"}

    try:
        if event.type == "payment_intent.succeeded":
            payment_intent_id = event_data.get("id")
            amount = float(event_data.get("amount_received", 0) / 100)
            logger.info("Stripe payment_intent.succeeded received for payment intent %s", payment_intent_id)
            payment = db.query(Payment).filter(Payment.transaction_ref == payment_intent_id).one_or_none()
            if payment:
                payment.status = "confirmed"
            tx = db.query(PaymentTransaction).filter(PaymentTransaction.stripe_payment_intent_id == payment_intent_id).one_or_none()
            if not tx and payment:
                tx = PaymentTransaction(
                    payment_id=payment.id,
                    stripe_payment_intent_id=payment_intent_id,
                    status="succeeded",
                    amount=amount,
                    currency=event_data.get("currency", "usd"),
                    payment_method=event_data.get("payment_method_types", [None])[0] if event_data.get("payment_method_types") else None,
                    metadata_json={"source": "stripe_webhook"},
                )
                db.add(tx)
            elif tx:
                tx.status = "succeeded"

            order = payment.order if payment else None
            order_id = getattr(order, "id", None)
            order_number = getattr(order, "order_number", None)
            order_user_id = getattr(order, "user_id", None)
            order_user = getattr(order, "user", None)
            order_email = getattr(order_user, "email", None) if order_user else None

            if user:
                services.notify_user(db, user, "Payment successful", f"Your payment of ${amount:.2f} has been confirmed.")

            if order:
                logger.info("Processing payment success for order %s from payment intent %s", order.id, payment_intent_id)
                existing_confirmation = db.query(AuditLog).filter(
                    AuditLog.action == "order_confirmation_email_sent",
                    AuditLog.resource_type == "order",
                    AuditLog.resource_id == str(order.id),
                ).one_or_none()
                if existing_confirmation:
                    logger.info("Order confirmation email already sent for order %s", order.id)
                    db.add(
                        AuditLog(
                            user_id=order_user_id,
                            actor_role="system",
                            action="order_confirmation_email_skipped",
                            resource_type="order",
                            resource_id=str(order.id),
                            message=f"Order confirmation email already sent for order {order_number or order.id}",
                            metadata_json={"payment_intent_id": payment_intent_id, "order_number": order_number},
                        )
                    )
                    db.commit()
                else:
                    logger.info("Triggering order confirmation email for order %s", order.id)
                    db.add(
                        AuditLog(
                            user_id=order_user_id,
                            actor_role="system",
                            action="order_confirmation_email_triggered",
                            resource_type="order",
                            resource_id=str(order.id),
                            message=f"Order confirmation email triggered for order {order_number or order.id}",
                            metadata_json={"payment_intent_id": payment_intent_id, "order_number": order_number},
                        )
                    )
                    db.commit()

                    email_sent = await services.send_order_confirmation_email(order, payment)
                    if email_sent:
                        db.add(
                            AuditLog(
                                user_id=order_user_id,
                                actor_role="system",
                                action="order_confirmation_email_sent",
                                resource_type="order",
                                resource_id=str(order.id),
                                message=f"Order confirmation email sent for order {order_number or order.id}",
                                metadata_json={"payment_intent_id": payment_intent_id, "order_number": order_number, "email": order_email},
                            )
                        )
                        logger.info("Order confirmation email sent for order %s", order.id)
                    else:
                        db.add(
                            AuditLog(
                                user_id=order_user_id,
                                actor_role="system",
                                action="order_confirmation_email_failed",
                                resource_type="order",
                                resource_id=str(order.id),
                                message=f"Order confirmation email failed for order {order_number or order.id}",
                                metadata_json={"payment_intent_id": payment_intent_id, "order_number": order_number, "email": order_email},
                            )
                        )
                        logger.warning("Order confirmation email failed for order %s", order.id)
                    db.commit()
            else:
                logger.warning("No order found for payment intent %s; skipping order confirmation email", payment_intent_id)

            db.add(
                AuditLog(
                    user_id=user.id if user else None,
                    actor_role="system",
                    action="payment_success",
                    resource_type="payment_intent",
                    resource_id=payment_intent_id,
                    message=f"Stripe payment {payment_intent_id} succeeded",
                    metadata_json={"amount": amount, "currency": event_data.get("currency", "usd")},
                )
            )
            db.add(
                FinancialLedger(
                    user_id=user.id if user else None,
                    wallet_id=None,
                    transaction_id=tx.id if tx else None,
                    entry_type="credit",
                    amount=amount,
                    currency=event_data.get("currency", "usd"),
                    memo="Stripe payment success",
                )
            )

        elif event.type == "payment_intent.payment_failed":
            payment_intent_id = event_data.get("id")
            payment = db.query(Payment).filter(Payment.transaction_ref == payment_intent_id).one_or_none()
            if payment:
                payment.status = "failed"
            if user:
                services.notify_user(db, user, "Payment failed", "Your payment could not be completed. Please try again.")
                services.send_email(
                    user.email,
                    "Payment Failed",
                    "<p>Your payment could not be completed. Please try again or use an alternate payment method.</p>",
                )
            db.add(
                AuditLog(
                    user_id=user.id if user else None,
                    actor_role="system",
                    action="payment_failed",
                    resource_type="payment_intent",
                    resource_id=payment_intent_id,
                    message=f"Stripe payment {payment_intent_id} failed",
                    metadata_json={"reason": (event_data.get("last_payment_error") or {}).get("message") if event_data.get("last_payment_error") else None},
                )
            )

        elif event.type == "invoice.paid":
            invoice_id = event_data.get("id")
            db.add(
                Invoice(
                    user_id=user.id,
                    order_id=None,
                    stripe_invoice_id=invoice_id,
                    status="paid",
                    amount_due=float(event_data.get("amount_due", 0) / 100),
                    amount_paid=float(event_data.get("amount_paid", 0) / 100),
                    currency=event_data.get("currency", "usd"),
                    due_date=datetime.fromtimestamp(event_data.get("due_date", 0)) if event_data.get("due_date") else None,
                    paid_at=datetime.utcnow(),
                    metadata_json={"source": "stripe_webhook"},
                )
            )
            if user:
                services.send_email(
                    user.email,
                    "Invoice Paid",
                    f"<p>Your invoice <strong>{invoice_id}</strong> has been paid successfully.</p>",
                )

        elif event.type == "invoice.payment_failed":
            db.add(
                AuditLog(
                    user_id=user.id if user else None,
                    actor_role="system",
                    action="invoice_payment_failed",
                    resource_type="invoice",
                    resource_id=event_data.get("id"),
                    message=f"Invoice {event_data.get('id')} payment failed",
                    metadata_json={"amount_due": float(event_data.get("amount_due", 0) / 100)},
                )
            )

        elif event.type == "customer.subscription.created":
            subscription = Subscription(
                user_id=user.id,
                stripe_subscription_id=event_data.get("id"),
                status=event_data.get("status", "active"),
                current_period_start=datetime.fromtimestamp(event_data.get("current_period_start", 0)) if event_data.get("current_period_start") else None,
                current_period_end=datetime.fromtimestamp(event_data.get("current_period_end", 0)) if event_data.get("current_period_end") else None,
                metadata_json={"source": "stripe_webhook"},
            )
            db.add(subscription)
            db.add(
                SubscriptionEvent(
                    subscription_id=subscription.id,
                    event_type=event.type,
                    event_id=event.id,
                    payload=event_data,
                )
            )

        elif event.type == "customer.subscription.updated":
            subscription = db.query(Subscription).filter(Subscription.stripe_subscription_id == event_data.get("id")).one_or_none()
            if not subscription:
                subscription = Subscription(
                    user_id=user.id,
                    stripe_subscription_id=event_data.get("id"),
                    status=event_data.get("status", "active"),
                    current_period_start=datetime.fromtimestamp(event_data.get("current_period_start", 0)) if event_data.get("current_period_start") else None,
                    current_period_end=datetime.fromtimestamp(event_data.get("current_period_end", 0)) if event_data.get("current_period_end") else None,
                    metadata_json={"source": "stripe_webhook"},
                )
                db.add(subscription)
            else:
                subscription.status = event_data.get("status", subscription.status)
                subscription.current_period_start = datetime.fromtimestamp(event_data.get("current_period_start", 0)) if event_data.get("current_period_start") else subscription.current_period_start
                subscription.current_period_end = datetime.fromtimestamp(event_data.get("current_period_end", 0)) if event_data.get("current_period_end") else subscription.current_period_end
            db.add(
                SubscriptionEvent(
                    subscription_id=subscription.id,
                    event_type=event.type,
                    event_id=event.id,
                    payload=event_data,
                )
            )

        elif event.type == "charge.refunded":
            db.add(
                AuditLog(
                    user_id=user.id if user else None,
                    actor_role="system",
                    action="charge_refunded",
                    resource_type="charge",
                    resource_id=event_data.get("id"),
                    message=f"Charge {event_data.get('id')} was refunded",
                    metadata_json={"amount": float(event_data.get("amount", 0) / 100)},
                )
            )

        stored_event.processed = True
        db.commit()
        return {"status": "success"}
    except Exception:
        logger.exception("Stripe webhook processing failed for event %s (%s)", event.id, event.type)
        db.rollback()
        raise
