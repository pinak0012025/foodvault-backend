from .stripe_client import StripeClient

class SubscriptionService:
    @staticmethod
    def create_subscription(customer_id, price_id, metadata=None):
        stripe = StripeClient.get_client()
        return stripe.Subscription.create(
            customer=customer_id,
            items=[{"price": price_id}],
            metadata=metadata or {}
        )
