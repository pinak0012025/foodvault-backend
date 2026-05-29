from .stripe_client import StripeClient
import stripe

class WebhookService:
    @staticmethod
    def verify_signature(payload, sig_header, endpoint_secret):
        stripe = StripeClient.get_client()
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
            return event
        except stripe.error.SignatureVerificationError:
            return None
