# Stripe Integration DB Migration Plan

This migration adds the following tables for Stripe and financial infrastructure:

- stripe_customers
- payment_transactions
- subscriptions
- subscription_events
- stripe_webhook_events
- financial_ledger
- invoices

All tables use UUID primary keys, have foreign keys, audit fields, and are indexed for performance.

**Migration Steps:**
1. Generate Alembic migration from `models_stripe.py`.
2. Apply migration to production DB.
3. Back up DB before migration.
4. Test all Stripe payment and subscription flows after migration.

**Note:**
- Ensure all new tables are included in Alembic's `env.py` target metadata.
- Review for naming conflicts or reserved words in your DB.
- Add any required indexes or constraints for production safety.
