import logging
from decimal import Decimal

import requests
from celery import shared_task
from django.conf import settings
from django.db import transaction

from .models import NotificationLog, PriceAlert

logger = logging.getLogger(__name__)


def should_trigger(current_price, threshold_price):
    """An alert fires when the price is at or below the threshold (equal counts)."""
    return Decimal(str(current_price)) <= Decimal(str(threshold_price))


@shared_task
def check_prices():
    """Runs every 60s via Celery Beat.

    For every route that has ACTIVE alerts: fetch the current price from our own
    mock feed and fire send_notification (async, via .delay) for each alert whose
    threshold is met. It never waits for notifications to be written.
    """
    active_alerts = PriceAlert.objects.filter(status=PriceAlert.Status.ACTIVE)
    routes = list(active_alerts.values_list("origin", "destination").distinct())
    fired = 0

    for origin, destination in routes:
        route = f"{origin}-{destination}"

        try:
            response = requests.get(
                settings.PRICE_FEED_URL,
                params={"route": route},
                timeout=settings.PRICE_FEED_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.warning("Price feed unreachable for %s: %s", route, exc)
            continue
        if response.status_code != 200:
            logger.info("No price for %s (HTTP %s), skipping", route, response.status_code)
            continue

        current_price = response.json().get("price")
        if current_price is None:
            continue

        route_alerts = active_alerts.filter(origin=origin, destination=destination)
        for alert in route_alerts:
            if should_trigger(current_price, alert.threshold_price):
                send_notification.delay(alert.id, current_price)
                fired += 1

    logger.info("check_prices: %s route(s) checked, %s notification(s) queued", len(routes), fired)
    return {"routes_checked": len(routes), "notifications_queued": fired}


@shared_task
def send_notification(alert_id, triggered_price):
    """Write a NotificationLog and mark the alert TRIGGERED so it never fires twice."""
    with transaction.atomic():
        try:
            alert = PriceAlert.objects.select_for_update().get(id=alert_id)
        except PriceAlert.DoesNotExist:
            return None
        # Idempotent: two overlapping check_prices runs (or a user deactivating the
        # alert in between) must not create duplicate/unwanted notifications.
        if alert.status != PriceAlert.Status.ACTIVE:
            return None

        message = (
            f"Price alert triggered! {alert.origin}-{alert.destination} "
            f"is now ₹{triggered_price} - below your threshold of "
            f"₹{alert.threshold_price}"
        )
        log = NotificationLog.objects.create(
            alert=alert, triggered_price=triggered_price, message=message
        )
        alert.status = PriceAlert.Status.TRIGGERED
        alert.save(update_fields=["status"])
    logger.info(message)
    return log.id
