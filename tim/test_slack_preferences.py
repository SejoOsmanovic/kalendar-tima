import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import JobRole, SlackLinkChallenge, SlackSubscription
from .slack_preferences import MAX_ATTEMPTS


@override_settings(SLACK_BOT_TOKEN="xoxb-test", SLACK_REMINDER_KEY="test-only")
class SlackPreferencesTests(TestCase):
    def setUp(self):
        self.lead = User.objects.create_user("team-lead")
        JobRole.objects.get(name="Video Editor").approvers.add(self.lead)
        self.url = reverse("slack_preferences")
        self.send = self.enterContext(patch("tim.slack_preferences.send_dm"))
        self.client.force_login(self.lead)

    def test_verified_connection_and_pause(self):
        self.assertContains(self.client.get(self.url), "<strong>Video Editor</strong>", html=True)
        response = self.client.post(self.url, {"action": "send_code", "member_id": "ULEAD1"})
        self.assertRedirects(response, self.url)
        self.assertFalse(SlackSubscription.objects.exists())
        message = self.send.call_args.args[0]
        self.assertEqual(self.send.call_args.kwargs["recipient"], "ULEAD1")
        code = re.search(r"code is ([0-9]{8})", message)[1]
        self.assertNotIn(code, SlackLinkChallenge.objects.get(user=self.lead).code_digest)
        self.client.post(self.url, {"action": "send_code", "member_id": "ULEAD1"})
        self.send.assert_called_once()

        self.assertRedirects(self.client.post(self.url, {"action": "verify_code", "code": code}), self.url)
        subscription = SlackSubscription.objects.get(user=self.lead)
        self.assertEqual(subscription.member_id, "ULEAD1")
        self.assertTrue(subscription.enabled)
        self.assertFalse(SlackLinkChallenge.objects.exists())
        self.client.post(self.url, {"action": "disable"})
        subscription.refresh_from_db()
        self.assertFalse(subscription.enabled)

    def test_a_code_cannot_be_reused_from_another_account_or_after_attempt_limit(self):
        self.client.post(self.url, {"action": "send_code", "member_id": "ULEAD1"})
        code = re.search(r"code is ([0-9]{8})", self.send.call_args.args[0])[1]
        another_admin = User.objects.create_user("another-admin", is_staff=True)
        self.client.force_login(another_admin)
        self.assertContains(self.client.post(self.url, {"action": "verify_code", "code": code}), "Request a new")
        self.client.force_login(self.lead)
        wrong_code = "00000000" if code != "00000000" else "11111111"
        for _ in range(MAX_ATTEMPTS):
            self.client.post(self.url, {"action": "verify_code", "code": wrong_code})
        self.client.post(self.url, {"action": "verify_code", "code": code})
        self.assertFalse(SlackSubscription.objects.exists())

    def test_connection_is_not_available_without_approval_access_or_csrf(self):
        member = User.objects.create_user("ordinary")
        self.client.force_login(member)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"action": "send_code", "member_id": "ULEAD1"}).status_code, 403)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.lead)
        self.assertEqual(protected.post(self.url, {"action": "send_code", "member_id": "ULEAD1"}).status_code, 403)
        self.send.assert_not_called()

    def test_expired_code_cannot_link(self):
        self.client.post(self.url, {"action": "send_code", "member_id": "ULEAD1"})
        code = re.search(r"code is ([0-9]{8})", self.send.call_args.args[0])[1]
        SlackLinkChallenge.objects.filter(user=self.lead).update(sent_at=timezone.now() - timedelta(minutes=11))
        self.client.post(self.url, {"action": "verify_code", "code": code})
        self.assertFalse(SlackSubscription.objects.exists())
