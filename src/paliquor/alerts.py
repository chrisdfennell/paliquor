"""Restock / price-drop alerts for watched products.

A user adds a Watch (email + product, optional target price). After each
catalog refresh we evaluate watches: if a product comes back in stock
(OUT/UNKNOWN -> IN_STOCK) or its price drops (below the target, if set), we
notify and record the state we notified on so we don't repeat.

Email goes out via SMTP if configured; otherwise alerts are logged, so the
feature is fully functional without credentials (useful in dev).
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import select

from .config import get_settings
from .db import session_scope
from .models import Product, Watch

log = logging.getLogger("paliquor.alerts")


def _send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.smtp_host:
        log.info("ALERT (no SMTP configured) -> %s | %s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"] = s.smtp_from or s.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port) as server:
        server.starttls()
        if s.smtp_user:
            server.login(s.smtp_user, s.smtp_password)
        server.send_message(msg)
    log.info("sent alert to %s: %s", to, subject)


def _back_in_stock(prev: str | None, now: str | None) -> bool:
    return (now or "").upper() == "IN_STOCK" and (prev or "").upper() != "IN_STOCK"


def _price_dropped(prev: float | None, now: float | None, target: float | None) -> bool:
    if now is None:
        return False
    if target is not None and now <= target and (prev is None or prev > target):
        return True
    return prev is not None and now < prev


def evaluate_watches() -> int:
    """Check all watches; send/log alerts for triggers. Returns alerts fired."""
    fired = 0
    with session_scope() as session:
        rows = session.execute(
            select(Watch, Product).join(Product, Watch.product_id == Product.id)
        ).all()
        for watch, product in rows:
            status, price = product.baseline_stock_status, product.price
            triggers: list[str] = []
            if _back_in_stock(watch.last_status, status):
                triggers.append(f"Back in stock statewide ({status}).")
            if _price_dropped(watch.last_price, price, watch.target_price):
                triggers.append(f"Price is now ${price:.2f}"
                                + (f" (was ${watch.last_price:.2f})" if watch.last_price else "")
                                + (f", at/under your ${watch.target_price:.2f} target"
                                   if watch.target_price else "") + ".")
            if triggers:
                body = (f"{product.name}\n\n" + "\n".join(triggers)
                        + f"\n\n{product.url}\n\n— PaLiquor watch")
                _send_email(watch.email, f"PaLiquor: {product.name}", body)
                fired += 1
            # Always advance the baseline so we alert on the next *change*.
            watch.last_status = status
            watch.last_price = price
    return fired
