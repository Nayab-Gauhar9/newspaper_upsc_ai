
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
import razorpay
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.database.models import PaymentTransaction, User
from src.database.session import get_db

router = APIRouter(prefix="/api/payments", tags=["payments"])

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")
BASE_APP_URL = os.getenv("BASE_APP_URL", "https://politymentor.com")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


class CreateOrderRequest(BaseModel):
    firebase_uid: str
    amount_in_paise: int = 49900
    tier_requested: str = "PRO_MONTHLY"
    currency: str = "INR"


class VerifyPaymentRequest(BaseModel):
    firebase_uid: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    tier_requested: str = "PRO_MONTHLY"


@router.post(
    "/create-order",
    status_code=status.HTTP_201_CREATED,
    summary="Create a Razorpay payment order and hosted payment link",
)
async def create_payment_order(
    payload: CreateOrderRequest,
    db: Session = Depends(get_db),
):
    try:
        # 1. Create standard Razorpay order
        order_data = {
            "amount": payload.amount_in_paise,
            "currency": payload.currency,
            "receipt": f"rcpt_{payload.firebase_uid[:10]}_{int(datetime.now().timestamp())}",
            "notes": {
                "firebase_uid": payload.firebase_uid,
                "tier_requested": payload.tier_requested,
            },
        }
        rzp_order = razorpay_client.order.create(data=order_data)
        order_id = rzp_order["id"]

        # 2. Create Razorpay Hosted Payment Link
        link_data = {
            "amount": payload.amount_in_paise,
            "currency": payload.currency,
            "accept_partial": False,
            "reference_id": order_id,
            "description": f"Polity Mentor {payload.tier_requested} Access",
            "customer": {
                "name": "Aspirant",
                "email": "aspirant@politymentor.com",
            },
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            "notes": {
                "firebase_uid": payload.firebase_uid,
                "tier_requested": payload.tier_requested,
                "order_id": order_id,
            },
            "callback_url": f"{BASE_APP_URL}/homepage",
            "callback_method": "get",
        }
        plink = razorpay_client.payment_link.create(link_data)
        payment_link_url = plink.get("short_url")

        # 3. Persist pending transaction in Neon DB (Synchronous)
        new_tx = PaymentTransaction(
            firebase_uid=payload.firebase_uid,
            razorpay_order_id=order_id,
            amount_in_paise=payload.amount_in_paise,
            currency=payload.currency,
            tier_requested=payload.tier_requested,
            status="CREATED",
            created_at=datetime.now(timezone.utc),
        )
        db.add(new_tx)
        db.commit()

        return {
            "order_id": order_id,
            "amount": payload.amount_in_paise,
            "currency": payload.currency,
            "key_id": RAZORPAY_KEY_ID,
            "firebase_uid": payload.firebase_uid,
            "payment_link_url": payment_link_url,
        }

    except Exception as e:
        db.rollback()
        print(f"[!] Error creating Razorpay order: {e}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate payment checkout: {str(e)}",
        )


@router.post(
    "/verify",
    status_code=status.HTTP_200_OK,
    summary="Client callback verification for Razorpay checkout",
)
async def verify_payment(
    payload: VerifyPaymentRequest,
    db: Session = Depends(get_db),
):
    generated_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(generated_signature, payload.razorpay_signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payment verification signature",
        )

    expiry_date = datetime.now(timezone.utc) + timedelta(days=30)

    # Synchronous DB updates
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
    db.commit()

    return {"status": "SUCCESS", "message": "Subscription upgraded successfully"}


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Razorpay webhook for automated server-side verification",
)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
    db: Session = Depends(get_db),
):
    print("\n" + "=" * 50, flush=True)
    print("[*] INCOMING RAZORPAY WEBHOOK HIT", flush=True)

    if not RAZORPAY_WEBHOOK_SECRET or not x_razorpay_signature:
        print("[!] Error: Missing webhook secret or x-razorpay-signature header", flush=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing webhook secret configuration or signature header",
        )

    body_bytes = await request.body()

    # 1. Validate HMAC signature
    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, x_razorpay_signature):
        print("[!] Signature verification failed!", flush=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook cryptographic signature",
        )

    print("[+] Signature successfully verified", flush=True)

    event_payload = await request.json()
    event_type = event_payload.get("event")
    print(f"[*] Event Type: {event_type}", flush=True)

    # 2. Extract payload entities
    payload_data = event_payload.get("payload", {})
    payment_entity = payload_data.get("payment", {}).get("entity", {})
    plink_entity = payload_data.get("payment_link", {}).get("entity", {})
    order_entity = payload_data.get("order", {}).get("entity", {})

    payment_id = payment_entity.get("id")
    order_id = payment_entity.get("order_id") or plink_entity.get("order_id")
    reference_id = plink_entity.get("reference_id")

    candidate_order_ids = [
        reference_id,
        order_id,
        payment_entity.get("order_id"),
        plink_entity.get("order_id"),
        order_entity.get("id"),
    ]
    candidate_order_ids = [cid for cid in candidate_order_ids if cid]

    merged_notes = {}
    if isinstance(order_entity.get("notes"), dict):
        merged_notes.update(order_entity["notes"])
    if isinstance(plink_entity.get("notes"), dict):
        merged_notes.update(plink_entity["notes"])
    if isinstance(payment_entity.get("notes"), dict):
        merged_notes.update(payment_entity["notes"])

    firebase_uid = merged_notes.get("firebase_uid")
    tier = merged_notes.get("tier_requested", "PRO_MONTHLY")

    print(f"[*] Payment ID: {payment_id}", flush=True)
    print(f"[*] Candidate Order IDs: {candidate_order_ids}", flush=True)
    print(f"[*] Extracted Notes: {merged_notes}", flush=True)
    print(f"[*] Initial Firebase UID: {firebase_uid}", flush=True)

    # 3. Synchronous DB query if UID is missing from notes
    existing_tx = None
    if candidate_order_ids:
        res = db.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.razorpay_order_id.in_(candidate_order_ids)
            )
        )
        existing_tx = res.scalar_one_or_none()

        if existing_tx:
            firebase_uid = firebase_uid or existing_tx.firebase_uid
            tier = tier or existing_tx.tier_requested
            print(
                f"[+] Found matching transaction in DB: id={existing_tx.id}, uid={existing_tx.firebase_uid}",
                flush=True,
            )
        else:
            print("[-] No existing PaymentTransaction matched candidate IDs in DB", flush=True)

    # 4. Synchronous updates
    if firebase_uid:
        expiry_date = datetime.now(timezone.utc) + timedelta(days=30)
        print(f"[*] Activating {tier} for UID: {firebase_uid} until {expiry_date}", flush=True)

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
        print("[+] User table statement executed", flush=True)

        if existing_tx:
            existing_tx.status = "SUCCESS"
            if payment_id:
                existing_tx.razorpay_payment_id = payment_id
            existing_tx.verified_at = datetime.now(timezone.utc)
            print("[+] Updated existing PaymentTransaction instance", flush=True)
        elif candidate_order_ids:
            stmt_tx = (
                update(PaymentTransaction)
                .where(PaymentTransaction.razorpay_order_id.in_(candidate_order_ids))
                .values(
                    status="SUCCESS",
                    razorpay_payment_id=payment_id,
                    verified_at=datetime.now(timezone.utc),
                )
            )
            db.execute(stmt_tx)
            print("[+] Executed fallback PaymentTransaction update statement", flush=True)

        db.commit()
        print("[+] SUCCESS: Database committed and subscription active!", flush=True)
    else:
        print("[!] FAILURE: Unable to identify firebase_uid from notes or DB lookup", flush=True)

    print("=" * 50 + "\n", flush=True)
    return {"status": "ok"}