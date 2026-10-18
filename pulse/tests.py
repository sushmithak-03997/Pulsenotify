from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import NotificationLog, PriceAlert, UserProfile
from .tasks import check_prices, send_notification, should_trigger


def make_alert(user, origin="DEL", destination="BOM", threshold=4500, **kwargs):
    return PriceAlert.objects.create(
        user=user, origin=origin, destination=destination, threshold_price=threshold, **kwargs
    )


def fake_feed(price, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"price": price}
    return resp


# ======================================================================
# REQUIRED TEST 1: threshold comparison logic (exercises the real helper)
# ======================================================================
class PriceThresholdTest(TestCase):
    def test_price_below_threshold_triggers_alert(self):
        self.assertTrue(should_trigger(4200, 4500))

    def test_price_above_threshold_does_not_trigger(self):
        self.assertFalse(should_trigger(5000, 4500))

    def test_price_equal_to_threshold_triggers_alert(self):
        self.assertTrue(should_trigger(4500, 4500))

    def test_decimal_threshold_from_database_is_compared_correctly(self):
        self.assertTrue(should_trigger(4500, Decimal("4500.00")))
        self.assertFalse(should_trigger(4501, Decimal("4500.00")))


# ======================================================================
# REQUIRED TEST 2: NotificationLog is created correctly (via the real task)
# ======================================================================
class NotificationLogTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.alert = make_alert(self.user, status=PriceAlert.Status.ACTIVE)

    def test_notification_log_created_with_correct_message(self):
        send_notification(self.alert.id, 4200)

        log = NotificationLog.objects.get(alert=self.alert)
        self.assertEqual(log.triggered_price, 4200)
        self.assertEqual(log.alert, self.alert)
        self.assertIn("DEL-BOM", log.message)
        self.assertIn("4200", log.message)

    def test_alert_marked_triggered_after_notification(self):
        send_notification(self.alert.id, 4200)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, PriceAlert.Status.TRIGGERED)

    def test_notification_is_idempotent(self):
        send_notification(self.alert.id, 4200)
        send_notification(self.alert.id, 4100)  # second delivery must be ignored
        self.assertEqual(NotificationLog.objects.count(), 1)

    def test_inactive_alert_gets_no_notification(self):
        self.alert.status = PriceAlert.Status.INACTIVE
        self.alert.save()
        send_notification(self.alert.id, 4200)
        self.assertEqual(NotificationLog.objects.count(), 0)

    def test_missing_alert_is_ignored(self):
        self.assertIsNone(send_notification(99999, 4200))


# ======================================================================
# REQUIRED TEST 3: alert scoping (through the real API)
# ======================================================================
class AlertScopingTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username="user1", password="pass1234")
        self.user2 = User.objects.create_user(username="user2", password="pass1234")
        self.alert1 = make_alert(self.user1, "DEL", "BOM", 4500)
        self.alert2 = make_alert(self.user2, "BLR", "HYD", 2000)
        self.client1 = APIClient()
        self.client1.force_authenticate(self.user1)

    def test_user_only_sees_own_alerts(self):
        resp = self.client1.get(reverse("alerts"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)
        self.assertEqual(resp.json()[0]["origin"], "DEL")

    def test_user_cannot_see_other_users_alerts(self):
        resp = self.client1.get(reverse("alerts"))
        origins = [a["origin"] for a in resp.json()]
        self.assertNotIn("BLR", origins)

    def test_user_with_no_alerts_gets_empty_list_not_404(self):
        user3 = User.objects.create_user(username="user3", password="pass1234")
        client = APIClient()
        client.force_authenticate(user3)
        resp = client.get(reverse("alerts"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_delete_other_users_alert_returns_404_and_changes_nothing(self):
        resp = self.client1.delete(reverse("alert-detail", args=[self.alert2.id]))
        self.assertEqual(resp.status_code, 404)
        self.alert2.refresh_from_db()
        self.assertEqual(self.alert2.status, PriceAlert.Status.ACTIVE)


# ======================================================================
# check_prices task (mocked price feed, real DB)
# ======================================================================
class CheckPricesTaskTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="traveller", password="pass1234")

    @patch("pulse.tasks.send_notification.delay")
    @patch("pulse.tasks.requests.get")
    def test_fires_notification_only_for_alerts_meeting_threshold(self, mock_get, mock_delay):
        hit = make_alert(self.user, "DEL", "BOM", 4500)
        make_alert(self.user, "DEL", "BOM", 3000)  # price 4200 > 3000 -> no
        mock_get.return_value = fake_feed(4200)

        result = check_prices()

        mock_delay.assert_called_once_with(hit.id, 4200)
        self.assertEqual(result, {"routes_checked": 1, "notifications_queued": 1})

    @patch("pulse.tasks.send_notification.delay")
    @patch("pulse.tasks.requests.get")
    def test_price_feed_called_once_per_route(self, mock_get, mock_delay):
        make_alert(self.user, "DEL", "BOM", 4500)
        make_alert(self.user, "DEL", "BOM", 5000)
        make_alert(self.user, "BLR", "HYD", 3000)
        mock_get.return_value = fake_feed(9999)

        check_prices()

        self.assertEqual(mock_get.call_count, 2)  # DEL-BOM and BLR-HYD
        mock_delay.assert_not_called()

    @patch("pulse.tasks.send_notification.delay")
    @patch("pulse.tasks.requests.get")
    def test_inactive_and_triggered_alerts_are_not_checked(self, mock_get, mock_delay):
        make_alert(self.user, status=PriceAlert.Status.INACTIVE)
        make_alert(self.user, status=PriceAlert.Status.TRIGGERED)
        check_prices()
        mock_get.assert_not_called()
        mock_delay.assert_not_called()

    @patch("pulse.tasks.send_notification.delay")
    @patch("pulse.tasks.requests.get")
    def test_unknown_route_404_is_skipped(self, mock_get, mock_delay):
        make_alert(self.user, "XXX", "YYY", 5000)
        mock_get.return_value = fake_feed(None, status=404)
        check_prices()
        mock_delay.assert_not_called()

    @patch("pulse.tasks.send_notification.delay")
    @patch("pulse.tasks.requests.get", side_effect=requests.ConnectionError("down"))
    def test_unreachable_feed_does_not_crash_the_task(self, mock_get, mock_delay):
        make_alert(self.user)
        result = check_prices()
        self.assertEqual(result["notifications_queued"], 0)

    @patch("pulse.tasks.requests.get")
    def test_end_to_end_creates_log_and_marks_triggered(self, mock_get):
        alert = make_alert(self.user, "DEL", "BOM", 4500)
        mock_get.return_value = fake_feed(4200)
        # Run .delay() synchronously so the whole chain executes inside the test.
        with patch.object(send_notification, "delay", side_effect=lambda *a: send_notification(*a)):
            check_prices()
        alert.refresh_from_db()
        self.assertEqual(alert.status, PriceAlert.Status.TRIGGERED)
        self.assertEqual(NotificationLog.objects.filter(alert=alert).count(), 1)

        # Next Beat tick: alert is TRIGGERED so nothing fires again.
        with patch.object(send_notification, "delay") as delay2:
            check_prices()
        delay2.assert_not_called()


# ======================================================================
# Auth endpoints
# ======================================================================
class AuthEndpointsTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_returns_201_token_and_user_role(self):
        resp = self.client.post(
            reverse("register"),
            {"username": "alice", "password": "securepass", "email": "alice@example.com"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["username"], "alice")
        self.assertEqual(body["role"], "user")
        self.assertTrue(body["access"])

    def test_register_ignores_role_in_body(self):
        resp = self.client.post(
            reverse("register"),
            {"username": "mallory", "password": "securepass", "role": "admin"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["role"], "user")
        self.assertEqual(User.objects.get(username="mallory").profile.role, UserProfile.Role.USER)

    def test_register_duplicate_username_returns_400(self):
        User.objects.create_user(username="alice", password="x12345678")
        resp = self.client.post(
            reverse("register"), {"username": "alice", "password": "securepass"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_post_save_signal_creates_profile(self):
        user = User.objects.create_user(username="bob", password="x12345678")
        self.assertEqual(user.profile.role, UserProfile.Role.USER)

    def test_superuser_profile_is_admin(self):
        su = User.objects.create_superuser(username="root", password="x12345678")
        self.assertEqual(su.profile.role, UserProfile.Role.ADMIN)

    def test_login_success_returns_token(self):
        User.objects.create_user(username="alice", password="securepass")
        resp = self.client.post(
            reverse("login"), {"username": "alice", "password": "securepass"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["access"])

    def test_login_wrong_password_returns_401(self):
        User.objects.create_user(username="alice", password="securepass")
        resp = self.client.post(
            reverse("login"), {"username": "alice", "password": "wrong"}, format="json"
        )
        self.assertEqual(resp.status_code, 401)

    def test_issued_token_grants_access_to_protected_endpoint(self):
        token = self.client.post(
            reverse("register"), {"username": "carol", "password": "securepass"}, format="json"
        ).json()["access"]
        resp = self.client.get(reverse("alerts"), HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(resp.status_code, 200)

    def test_protected_endpoints_require_token(self):
        self.assertEqual(self.client.get(reverse("alerts")).status_code, 401)
        self.assertEqual(self.client.get(reverse("admin-summary")).status_code, 401)


# ======================================================================
# Alert endpoints
# ======================================================================
class AlertEndpointsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="securepass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_create_alert_uses_request_user_and_ignores_body_user(self):
        other = User.objects.create_user(username="other", password="x12345678")
        resp = self.client.post(
            reverse("alerts"),
            {"origin": "del", "destination": "bom", "threshold_price": "4500", "user": other.id, "status": "triggered"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        alert = PriceAlert.objects.get(id=resp.json()["id"])
        self.assertEqual(alert.user, self.user)
        self.assertEqual(alert.origin, "DEL")  # normalised
        self.assertEqual(alert.status, PriceAlert.Status.ACTIVE)  # status not writable

    def test_create_alert_validation(self):
        bad = [
            {"origin": "DEL", "destination": "BOM", "threshold_price": "-5"},
            {"origin": "DEL", "destination": "DEL", "threshold_price": "100"},
            {"origin": "DEL"},
        ]
        for payload in bad:
            self.assertEqual(self.client.post(reverse("alerts"), payload, format="json").status_code, 400)

    def test_delete_sets_inactive_but_keeps_row(self):
        alert = make_alert(self.user)
        resp = self.client.delete(reverse("alert-detail", args=[alert.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "inactive"})
        alert.refresh_from_db()
        self.assertEqual(alert.status, PriceAlert.Status.INACTIVE)

    def test_delete_nonexistent_alert_returns_404(self):
        self.assertEqual(self.client.delete(reverse("alert-detail", args=[424242])).status_code, 404)


# ======================================================================
# Mock price feed
# ======================================================================
class PriceFeedTest(TestCase):
    def test_returns_price_inside_range_without_auth(self):
        for _ in range(25):
            resp = APIClient().get(reverse("flight-price"), {"route": "DEL-BOM"})
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["route"], "DEL-BOM")
            self.assertIsInstance(body["price"], int)
            self.assertTrue(3000 <= body["price"] <= 7000)

    def test_unknown_route_returns_404(self):
        self.assertEqual(APIClient().get(reverse("flight-price"), {"route": "ZZZ-YYY"}).status_code, 404)

    def test_missing_route_returns_404(self):
        self.assertEqual(APIClient().get(reverse("flight-price")).status_code, 404)


# ======================================================================
# Admin summary
# ======================================================================
class AdminSummaryTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="boss", password="x12345678")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()
        self.user = User.objects.create_user(username="alice", password="x12345678")

        a1 = make_alert(self.user, "DEL", "BOM", status=PriceAlert.Status.ACTIVE)
        make_alert(self.user, "DEL", "BOM", status=PriceAlert.Status.ACTIVE)
        make_alert(self.user, "BLR", "HYD", status=PriceAlert.Status.TRIGGERED)
        make_alert(self.user, "DEL", "BLR", status=PriceAlert.Status.INACTIVE)
        NotificationLog.objects.create(alert=a1, triggered_price=4000, message="m")

    def test_regular_user_gets_403(self):
        client = APIClient()
        client.force_authenticate(self.user)
        self.assertEqual(client.get(reverse("admin-summary")).status_code, 403)

    def test_admin_gets_correct_statistics(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        resp = client.get(reverse("admin-summary"))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total_alerts"], 4)
        self.assertEqual(body["active_alerts"], 2)
        self.assertEqual(body["triggered_alerts"], 1)
        self.assertEqual(body["total_notifications"], 1)
        self.assertEqual(body["top_routes"][0], {"route": "DEL-BOM", "alert_count": 2})
        self.assertEqual(len(body["top_routes"]), 3)

    def test_empty_database_returns_zeroes(self):
        PriceAlert.objects.all().delete()
        client = APIClient()
        client.force_authenticate(self.admin)
        body = client.get(reverse("admin-summary")).json()
        self.assertEqual(body["total_alerts"], 0)
        self.assertEqual(body["active_alerts"], 0)
        self.assertEqual(body["top_routes"], [])
