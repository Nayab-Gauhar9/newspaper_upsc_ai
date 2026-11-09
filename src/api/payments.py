import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import PaymentTransaction, User
from src.database.session import get_db
from src.schema.payments import (
    CreateOrderRequest,
    CreateOrderResponse,
    VerifyPaymentRequest,
    VerifyPaymentResponse,
)
from src.services.payment_service import PaymentService

router = APIRouter(prefix="/api/payments", tags=["payments"])

RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")


@router.post(
    "/create-order",
    response_model=CreateOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Razorpay payment order",
)
async def create_payment_order(
    payload: CreateOrderRequest,
    db: AsyncSession = Depends(get_db),
):
    return await PaymentService.create_order(db, payload)


@router.post(
    "/verify",
    response_model=VerifyPaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify payment signature and activate subscription",
)
async def verify_payment(
    payload: VerifyPaymentRequest,
    db: AsyncSession = Depends(get_db),
):
    return await PaymentService.verify_and_activate(db, payload)


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Razorpay webhook for automated server-side verification",
)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    if not RAZORPAY_WEBHOOK_SECRET or not x_razorpay_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing webhook secret configuration or signature header",
        )

    body_bytes = await request.body()

    # Validate Webhook HMAC-SHA256 signature
    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, x_razorpay_signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook cryptographic signature",
        )

    event_payload = await request.json()
    event_type = event_payload.get("event")

    # Handle successful captures and payment links
    if event_type in ["payment.captured", "payment_link.paid"]:
        payment_entity = (
            event_payload.get("payload", {}).get("payment", {}).get("entity", {})
        )
        order_id = payment_entity.get("order_id")
        payment_id = payment_entity.get("id")
        notes = payment_entity.get("notes", {})
        firebase_uid = notes.get("firebase_uid")
        tier = notes.get("tier_requested", "PRO_MONTHLY")

        if firebase_uid:
            expiry_date = datetime.now(timezone.utc) + timedelta(days=30)

            # Idempotently update user subscription status in Neon DB
            stmt_user = (
                update(User)
                .where(User.firebase_uid == firebase_uid)
                .values(
                    subscription_tier=tier,
                    subscription_status="ACTIVE",
                    current_period_end=expiry_date,
                )
            )
            db.execute(stmt_user)

            if order_id:
                stmt_tx = (
                    update(PaymentTransaction)
                    .where(PaymentTransaction.razorpay_order_id == order_id)
                    .values(
                        status="SUCCESS",
                        razorpay_payment_id=payment_id,
                        verified_at=datetime.now(timezone.utc),
                    )
                )
                db.execute(stmt_tx)

            db.commit()

    return {"status": "ok"}