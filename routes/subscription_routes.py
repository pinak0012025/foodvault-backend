from fastapi import APIRouter, Depends, HTTPException
from backend.stripe.subscription_service import SubscriptionService

router = APIRouter()

@router.post("/subscriptions/create")
async def create_subscription(customer_id: str, price_id: str):
    try:
        subscription = SubscriptionService.create_subscription(customer_id, price_id)
        return {"subscription_id": subscription.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
