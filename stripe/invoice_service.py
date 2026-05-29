from .stripe_client import StripeClient

class InvoiceService:
    @staticmethod
    def create_invoice(customer_id, auto_advance=True, metadata=None):
        stripe = StripeClient.get_client()
        return stripe.Invoice.create(
            customer=customer_id,
            auto_advance=auto_advance,
            metadata=metadata or {}
        )
