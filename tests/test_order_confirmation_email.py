from decimal import Decimal
from types import SimpleNamespace

from services import build_order_confirmation_email


def test_build_order_confirmation_email_includes_order_details():
    product = SimpleNamespace(name="Emergency Kit", price=Decimal("25.00"), lock_duration_days=60)
    order_item = SimpleNamespace(product=product, quantity=2, total_price=Decimal("50.00"), reserve_type="reserve")
    order = SimpleNamespace(
        order_number="FV-202606-001",
        total_amount=Decimal("50.00"),
        items=[order_item],
        user=SimpleNamespace(email="customer@example.com"),
    )
    payment = SimpleNamespace(amount=Decimal("50.00"))

    subject, html_body, text_body = build_order_confirmation_email(order, payment)

    assert subject == "FoodVault Order Confirmation"
    assert "FV-202606-001" in html_body
    assert "Emergency Kit" in html_body
    assert "2x Emergency Kit" in html_body
    assert "$50.00" in html_body
    assert "60 days" in html_body
    assert "Your order has been confirmed" in html_body
    assert "Order ID: FV-202606-001" in text_body
