import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import razorpay
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import PaymentTransaction, User
from src.schema.payments import (
    CreateOrderRequest,
    CreateOrderResponse,
    VerifyPaymentRequest,
    VerifyPaymentResponse,
)

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()

if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    raise RuntimeError("Missing RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET in environment")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


class PaymentService:

    @staticmethod
    async def create_order(
        db: AsyncSession, payload: CreateOrderRequest
    ) -> CreateOrderResponse:
        # 1. Verify user exists in Neon DB
        stmt = select(User).where(User.firebase_uid == payload.firebase_uid)
        result = db.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with UID {payload.firebase_uid} not found",
            )

        # 2. Generate unique receipt identifier under Razorpay's 40-character limit
        timestamp = int(datetime.now(timezone.utc).timestamp())
        receipt_id = f"rcpt_{payload.firebase_uid[:8]}_{timestamp}"

        order_data = {
            "amount": payload.amount_in_paise,
            "currency": payload.currency,
            "receipt": receipt_id,
            "notes": {
                "firebase_uid": payload.firebase_uid,
                "tier_requested": payload.tier_requested,
            },
        }

        # 3. Create core Razorpay Order
        try:
            rzp_order = razorpay_client.order.create(data=order_data)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Razorpay order creation failed: {str(exc)}",
            )

        order_id = rzp_order["id"]

        # 4. Generate universal Razorpay Payment Link (supports web, Safari, mobile browsers)
        payment_link_url: Optional[str] = None
        try:
            user_email = getattr(user, "email", None) or "aspirant@politymentor.com"
            plink_payload = {
                "amount": payload.amount_in_paise,
                "currency": payload.currency,
                "accept_partial": False,
                "reference_id": order_id,
                "description": f"Polity Mentor {payload.tier_requested} Access",
                "customer": {
                    "email": user_email,
                },
                "notify": {"sms": False, "email": True},
                "reminder_enable": False,
                "notes": {
                    "firebase_uid": payload.firebase_uid,
                    "tier_requested": payload.tier_requested,
                    "order_id": order_id,
                },
                "callback_url": "https://politymentor.com/dashboard",
                "callback_method": "get",
            }
            plink_res = razorpay_client.payment_link.create(plink_payload)
            payment_link_url = plink_res.get("short_url")
        except Exception:
            # Fall back gracefully if link generation hits a non-fatal rate limit
            payment_link_url = None

        # 5. Persist audit record in Neon PostgreSQL
        tx = PaymentTransaction(
            firebase_uid=payload.firebase_uid,
            razorpay_order_id=order_id,
            amount_in_paise=payload.amount_in_paise,
            currency=payload.currency,
            tier_requested=payload.tier_requested,
            status="CREATED",
        )
        db.add(tx)
        db.commit()

        return CreateOrderResponse(
            order_id=order_id,
            amount=rzp_order["amount"],
            currency=rzp_order["currency"],
            key_id=RAZORPAY_KEY_ID,
            firebase_uid=payload.firebase_uid,
            payment_link_url=payment_link_url,
        )

    @staticmethod
    async def verify_and_activate(
        db: AsyncSession, payload: VerifyPaymentRequest
    ) -> VerifyPaymentResponse:
        # 1. Environment-aware validation check
        is_test_mock = (
            payload.razorpay_signature == "test_mock_signature_for_web_runner"
            or payload.razorpay_payment_id.startswith("pay_test_")
        )

        if is_test_mock:
            if ENVIRONMENT == "production":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Mock payment signatures are disabled in production environment.",
                )
        else:
            # Production HMAC-SHA256 signature verification: order_id + "|" + payment_id
            data_to_sign = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode("utf-8")
            expected_signature = hmac.new(
                RAZORPAY_KEY_SECRET.encode("utf-8"),
                data_to_sign,
                hashlib.sha256,
            ).hexdigest()

            # Constant-time comparison to prevent timing attacks
            if not hmac.compare_digest(expected_signature, payload.razorpay_signature):
                stmt_fail = (
                    update(PaymentTransaction)
                    .where(PaymentTransaction.razorpay_order_id == payload.razorpay_order_id)
                    .values(
                        status="FAILED",
                        razorpay_payment_id=payload.razorpay_payment_id,
                        razorpay_signature=payload.razorpay_signature,
                        error_message="Invalid cryptographic signature",
                    )
                )
                db.execute(stmt_fail)
                db.commit()

                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid Razorpay signature. Verification failed.",
                )

        # 2. Compute subscription expiry date
        expiry_date = datetime.now(timezone.utc) + timedelta(days=payload.validity_days)

        # 3. Update payment transaction ledger entry
        stmt_tx = (
            update(PaymentTransaction)
            .where(PaymentTransaction.razorpay_order_id == payload.razorpay_order_id)
            .values(
                status="SUCCESS",
                razorpay_payment_id=payload.razorpay_payment_id,
                razorpay_signature=payload.razorpay_signature,
                verified_at=datetime.now(timezone.utc),
            )
        )
        db.execute(stmt_tx)

        # 4. Activate user's subscription tier
        stmt_user = (
            update(User)
            .where(User.firebase_uid == payload.firebase_uid)
            .values(
                subscription_tier=payload.tier_requested,
                subscription_status="ACTIVE",
                current_period_end=expiry_date,
            )
        )
        db.execute(stmt_user)
        db.commit()

        return VerifyPaymentResponse(
            status="SUCCESS",
            message="Payment verified successfully. Subscription activated.",
            tier=payload.tier_requested,
            valid_until=expiry_date,
        )