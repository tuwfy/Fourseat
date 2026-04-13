"""
Stripe billing helpers for Fourseat signup checkout.
"""

import os
from urllib.parse import urlencode


def create_checkout_session(email: str, name: str = "") -> dict:
    secret_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    price_id = os.getenv("STRIPE_PRICE_ID", "").strip()
    base_url = os.getenv("APP_BASE_URL", "http://localhost:5000").strip().rstrip("/")

    if not secret_key or not price_id:
        # Waitlist is already stored; Stripe checkout is optional until env is configured.
        return {
            "success": True,
            "checkout_url": None,
            "billing_available": False,
            "message": "You're on the list. We'll email you with next steps.",
        }

    success_url = f"{base_url}/?trial=1#debate"
    cancel_url = f"{base_url}/#waitlist"

    payload = {
        "mode": "subscription",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "allow_promotion_codes": "true",
    }
    if email:
        payload["customer_email"] = email
    if name:
        payload["metadata[name]"] = name

    try:
        import requests
        response = requests.post(
            "https://api.stripe.com/v1/checkout/sessions",
            headers={
                "Authorization": f"Bearer {secret_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=urlencode(payload),
            timeout=20,
        )
        if response.status_code >= 400:
            try:
                err = response.json().get("error", {}).get("message", response.text)
            except Exception:
                err = response.text
            return {"success": False, "error": f"Stripe error: {err}"}

        data = response.json()
        return {
            "success": True,
            "checkout_url": data.get("url"),
            "session_id": data.get("id"),
        }
    except Exception as exc:
        return {"success": False, "error": f"Unable to create checkout session: {exc}"}
