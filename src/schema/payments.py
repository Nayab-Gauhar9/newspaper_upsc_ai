from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class CreateOrderRequest(BaseModel):
    firebase_uid: str = Field(..., description="Firebase UID of the aspirant")
    amount_in_paise: int = Field(..., gt=0, description="Amount in paise (e.g. 49900 for Rs 499)")
    tier_requested: str = Field(default="PRO_MONTHLY", description="Requested tier identifier")
    currency: str = Field(default="INR", description="Three-letter currency code")

class CreateOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str
    firebase_uid: str
    payment_link_url: Optional[str] = None

class VerifyPaymentRequest(BaseModel):
    firebase_uid: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    tier_requested: str
    validity_days: int = Field(default=30, ge=1)

class VerifyPaymentResponse(BaseModel):
    status: str
    message: str
    tier: str
    valid_until: datetime