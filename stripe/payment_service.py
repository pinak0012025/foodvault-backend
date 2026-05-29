from .stripe_client import StripeClient


class PaymentService:
    @staticmethod
    def create_customer(email: str, metadata: dict | None = None):
        stripe = StripeClient.get_client()
        return stripe.Customer.create(email=email, metadata=metadata or {})

    @staticmethod
    def create_payment_intent(
        amount_cents: int,
        currency: str,
        customer_id: str | None = None,
        metadata: dict | None = None,
        payment_method_types: list[str] | None = None,
        receipt_email: str | None = None,
    ):
        stripe = StripeClient.get_client()
        params = {
            "amount": amount_cents,
            "currency": currency,
            "metadata": metadata or {},
            "automatic_payment_methods": {"enabled": True},
        }
        if payment_method_types:
            params.pop("automatic_payment_methods", None)
            params["payment_method_types"] = payment_method_types
        if customer_id:
            params["customer"] = customer_id
        if receipt_email:
            params["receipt_email"] = receipt_email
        return stripe.PaymentIntent.create(**params)
