import stripe
from backend.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

if not stripe.api_key:
    print("[stripe] WARNING: STRIPE_SECRET_KEY not configured - Stripe operations will fail", flush=True)
else:
    print(f"[stripe] Initialized with secret key: {stripe.api_key[:20]}...", flush=True)

class StripeClient:
    @staticmethod
    def get_client():
        if not stripe.api_key:
            raise RuntimeError("Stripe API key not configured. Set STRIPE_SECRET_KEY environment variable.")
        return stripe
