from decimal import Decimal

from routes.payment_routes import calculate_checkout_totals


def test_calculate_checkout_totals_uses_planner_lock_amount_for_reserves():
    payload = {
        "amount": "184.00",
        "currency": "usd",
        "items": [
            {"product_id": 1, "quantity": 1, "reserve_option": "reserve"},
            {"product_id": 2, "quantity": 1, "reserve_option": "purchase"},
        ],
        "reserve_total_value": "200.00",
        "upfront_amount": "75.00",
        "remaining_balance": "125.00",
        "membership_selected": True,
        "membership_fee": "29.00",
    }

    product_lookup = {
        1: {
            "price": Decimal("40.00"),
            "locked_price": Decimal("40.00"),
            "reserve_lock_price": None,
        },
        2: {
            "price": Decimal("80.00"),
            "locked_price": Decimal("80.00"),
            "reserve_lock_price": None,
        },
    }

    totals = calculate_checkout_totals(payload, product_lookup)

    assert totals["purchase_total"] == Decimal("80.00")
    assert totals["reserve_upfront"] == Decimal("75.00")
    assert totals["membership_fee"] == Decimal("29.00")
    assert totals["expected_amount"] == Decimal("184.00")
    assert totals["reserve_total_value"] == Decimal("200.00")
    assert totals["remaining_balance"] == Decimal("125.00")


def test_calculate_checkout_totals_falls_back_to_locked_product_price_when_no_upfront_override():
    payload = {
        "items": [
            {"product_id": 1, "quantity": 2, "reserve_option": "reserve"},
        ]
    }

    product_lookup = {
        1: {
            "price": Decimal("20.00"),
            "locked_price": Decimal("25.00"),
            "reserve_lock_price": None,
        }
    }

    totals = calculate_checkout_totals(payload, product_lookup)

    assert totals["reserve_upfront"] == Decimal("50.00")
    assert totals["expected_amount"] == Decimal("50.00")


def test_calculate_checkout_totals_accepts_string_product_ids():
    payload = {
        "items": [
            {"product_id": "1", "quantity": 1, "reserve_option": "purchase"},
        ]
    }

    product_lookup = {
        1: {
            "price": Decimal("15.00"),
            "locked_price": None,
            "reserve_lock_price": None,
            "name": "Test Product",
        }
    }

    totals = calculate_checkout_totals(payload, product_lookup)

    assert totals["purchase_total"] == Decimal("15.00")
    assert totals["expected_amount"] == Decimal("15.00")
