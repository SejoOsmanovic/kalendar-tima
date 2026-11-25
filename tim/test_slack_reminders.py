from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Day, JobRole, LeaveRequest, MemberRole, SlackReminderDelivery, SlackSubscription
from .slack_reminders import CROWDED_SAMPLE_NAMES, SlackDeliveryError


@override_settings(
    TIME_ZONE="Europe/Sarajevo",
    SLACK_REMINDER_KEY="scheduler-test-key",
    SLACK_BOT_TOKEN="xoxb-test-token",
    SLACK_RECIPIENT_ID="UOWNER1",
)
class SlackReminderTests(TestCase):
    friday_afternoon = datetime(2026, 11, 27, 16, 5, tzinfo=timezone.utc)
    monday = date(2026, 11, 30)

    def setUp(self):
        self.scheduler = Client(
            enforce_csrf_checks=True,
            headers={"authorization": "Bearer scheduler-test-key"},
        )
        self.endpoint = reverse("slack_reminder")
        self.test_endpoint = reverse("slack_reminder_test")
        self.slack = self.enterContext(patch("tim.slack_reminders.requests.post"))
        self.slack.side_effect = self.slack_response

    def slack_response(self, url, **kwargs):
        response = Mock()
        if url.endswith("/conversations.open"):
            response.json.return_value = {
                "ok": True,
                "channel": {"id": "DPRIVATE1", "is_im": True, "user": "UOWNER1"},
            }
        else:
            response.json.return_value = {"ok": True}
        return response

    def add_day(self, username, kind, target=None, status=None, **user_fields):
        worker = User.objects.create_user(username, **user_fields)
        when = target or self.monday
        source = None
        if status:
            source = LeaveRequest.objects.create(
                worker=worker, start=when, end=when, kind=kind, status=status, note="Private note",
            )
        return Day.objects.create(worker=worker, date=when, kind=kind, source=source)

    def test_friday_rolls_forward_to_monday_and_sends_one_private_summary(self):
        self.add_day("ana", "free", status="approved", first_name="Ana <@UOTHER>")
        self.add_day("marko", "vacation", first_name="Marko")
        self.add_day("weekend", "free", date(2026, 11, 28))
        self.add_day("archived", "free", is_active=False)
        self.add_day("holiday", "holiday")
        self.add_day("sick", "sick")
        self.add_day("pending", "free", status="pending")

        with patch("tim.slack_reminders.timezone.now", return_value=self.friday_afternoon):
            self.assertEqual(self.scheduler.post(self.endpoint).status_code, 204)
            self.assertEqual(self.scheduler.post(self.endpoint).status_code, 204)

        self.assertEqual(self.slack.call_count, 2)
        open_dm, post_message = self.slack.call_args_list
        self.assertEqual(open_dm.args[0], "https://slack.com/api/conversations.open")
        self.assertEqual(open_dm.kwargs["json"]["users"], "UOWNER1")
        self.assertEqual(post_message.args[0], "https://slack.com/api/chat.postMessage")
        payload = post_message.kwargs["json"]
        self.assertEqual(payload["channel"], "DPRIVATE1")
        self.assertIn("Monday, November 30, 2026", payload["text"])
        self.assertIn("Ana &lt;@UOTHER&gt;", payload["text"])
        self.assertIn("Marko", payload["text"])
        self.assertIn("?dan=2026-11-30", payload["text"])
        for excluded in ("weekend", "archived", "holiday", "sick", "pending", "Private note"):
            self.assertNotIn(excluded, payload["text"])
        self.assertTrue(SlackReminderDelivery.objects.filter(absence_date=self.monday).exists())

    def test_regular_workday_empty_days_and_weekend(self):
        self.add_day("tuesday", "free", date(2026, 12, 1))
        times_without_reminders = (
            datetime(2026, 11, 28, 16, 5, tzinfo=timezone.utc),  # Saturday
            datetime(2026, 11, 30, 8, 0, tzinfo=timezone.utc),  # Monday morning
            datetime(2026, 12, 1, 16, 5, tzinfo=timezone.utc),  # No absences on Wednesday
        )
        for now in times_without_reminders:
            with patch("tim.slack_reminders.timezone.now", return_value=now):
                self.assertEqual(self.scheduler.post(self.endpoint).status_code, 204)
        self.slack.assert_not_called()

        monday_afternoon = datetime(2026, 11, 30, 16, 5, tzinfo=timezone.utc)
        with patch("tim.slack_reminders.timezone.now", return_value=monday_afternoon):
            self.assertEqual(self.scheduler.post(self.endpoint).status_code, 204)
        self.assertIn("Tuesday, December 1, 2026", self.slack.call_args.kwargs["json"]["text"])

    def test_missing_key_and_site_user_cannot_trigger_delivery(self):
        admin = User.objects.create_user("admin", is_staff=True)
        self.client.force_login(admin)
        self.assertEqual(self.client.post(self.test_endpoint).status_code, 403)
        self.assertEqual(self.scheduler.get(self.test_endpoint).status_code, 405)
        with self.settings(SLACK_REMINDER_KEY=""):
            self.assertEqual(self.scheduler.post(self.test_endpoint).status_code, 403)
        self.slack.assert_not_called()

    def test_manual_test_has_no_employee_data_and_does_not_mark_delivery(self):
        self.add_day("private-employee-name", "free")
        with patch("tim.slack_reminders.timezone.now", return_value=self.friday_afternoon):
            self.assertEqual(self.scheduler.post(self.test_endpoint).status_code, 204)
        payload = self.slack.call_args.kwargs["json"]
        self.assertIn("TEST · Days off on Monday, November 30, 2026", payload["text"])
        self.assertIn("Sample team member", payload["text"])
        self.assertNotIn("private-employee-name", payload["text"])
        self.assertFalse(SlackReminderDelivery.objects.exists())

        with patch("tim.slack_reminders.timezone.now", return_value=self.friday_afternoon):
            self.assertEqual(self.scheduler.post(reverse("slack_reminder_test_group")).status_code, 204)
        group_text = self.slack.call_args.kwargs["json"]["text"]
        self.assertIn("TEST · Days off on Monday, November 30, 2026", group_text)
        self.assertEqual(
            [line.removeprefix("• ") for line in group_text.splitlines() if line.startswith("• ")],
            list(CROWDED_SAMPLE_NAMES),
        )
        self.assertNotIn("private-employee-name", group_text)
        self.assertFalse(SlackReminderDelivery.objects.exists())

    def test_admin_sends_a_sample_to_only_the_selected_linked_member(self):
        admin = User.objects.create_user("admin", is_staff=True)
        target = User.objects.create_user("lea", first_name="Léa", last_name="Đurić")
        other = self.add_day("another-member", "free", date(2026, 11, 26)).worker
        SlackSubscription.objects.create(user=target, member_id="UTARGET1")
        SlackSubscription.objects.create(user=other, member_id="UOTHER1")
        self.client.force_login(admin)
        endpoint = reverse("send_member_slack_test", args=[target.pk])
        self.assertContains(self.client.get(reverse("team")), f'action="{endpoint}"')

        wednesday = datetime(2026, 11, 25, 10, tzinfo=timezone.utc)
        with patch("tim.slack_reminders.timezone.now", return_value=wednesday), patch(
            "tim.slack_reminders.send_dm",
        ) as send:
            response = self.client.post(endpoint, follow=True)

        self.assertContains(response, "Slack test sent to Léa Đurić.")
        send.assert_called_once_with(
            "TEST · Days off on Thursday, November 26, 2026\n"
            "• Léa Đurić\n\nSample reminder from Scale Up Vacation Tracker.",
            recipient="UTARGET1",
        )
        self.assertFalse(Day.objects.filter(worker=target).exists())
        self.assertFalse(SlackReminderDelivery.objects.exists())

    def test_member_slack_test_requires_a_full_admin_and_enabled_subscription(self):
        administrator = User.objects.create_user("admin", is_staff=True)
        lead = User.objects.create_user("lead")
        JobRole.objects.get(name="Video Editor").approvers.add(lead)
        target = User.objects.create_user("member")
        SlackSubscription.objects.create(user=target, member_id="UTARGET1", enabled=False)
        endpoint = reverse("send_member_slack_test", args=[target.pk])

        self.client.force_login(lead)
        self.assertEqual(self.client.post(endpoint).status_code, 403)
        self.client.force_login(administrator)
        self.assertEqual(self.client.get(endpoint).status_code, 405)
        self.assertEqual(self.client.post(endpoint).status_code, 404)
        self.assertNotContains(self.client.get(reverse("team")), f'action="{endpoint}"')
        self.slack.assert_not_called()

    def test_mismatched_dm_is_rejected(self):
        response = Mock()
        response.json.return_value = {
            "ok": True,
            "channel": {"id": "DOTHER1", "is_im": True, "user": "UOTHER"},
        }
        self.slack.side_effect = None
        self.slack.return_value = response
        with self.assertLogs("tim.slack_reminders", level="WARNING"):
            self.assertEqual(self.scheduler.post(self.test_endpoint).status_code, 502)
        self.assertEqual(self.slack.call_count, 1)

    def test_failed_delivery_can_be_retried(self):
        self.add_day("ana", "free")
        failed = Mock()
        failed.json.return_value = {"ok": False, "error": "internal_error"}
        self.slack.side_effect = [self.slack_response("https://slack.com/api/conversations.open"), failed]

        with patch("tim.slack_reminders.timezone.now", return_value=self.friday_afternoon):
            with self.assertLogs("tim.slack_reminders", level="WARNING"):
                self.assertEqual(self.scheduler.post(self.endpoint).status_code, 502)
            self.assertFalse(SlackReminderDelivery.objects.exists())
            self.slack.side_effect = self.slack_response
            self.assertEqual(self.scheduler.post(self.endpoint).status_code, 204)

        self.assertTrue(SlackReminderDelivery.objects.filter(absence_date=self.monday).exists())

    def test_full_admin_and_lead_receive_only_their_current_scope(self):
        full_admin = User.objects.create_user("owner", is_staff=True)
        editor_lead = User.objects.create_user("editor-lead")
        worker = User.objects.create_user("ordinary-member")
        former_lead = User.objects.create_user("former-lead")
        SlackSubscription.objects.create(user=full_admin, member_id="UOWNER1")
        SlackSubscription.objects.create(user=editor_lead, member_id="ULEAD1")
        SlackSubscription.objects.create(user=worker, member_id="UWORKER1", team_overview=True)
        SlackSubscription.objects.create(user=former_lead, member_id="UFORMER1")

        editor_role = JobRole.objects.get(name="Video Editor")
        buyer_role = JobRole.objects.get(name="Media Buyer")
        editor_role.approvers.add(editor_lead)
        editor = self.add_day("editor", "free", first_name="Video editor").worker
        buyer = self.add_day("buyer", "free", first_name="Media buyer").worker
        MemberRole.objects.create(user=editor, role=editor_role)
        MemberRole.objects.create(user=buyer, role=buyer_role)
        Day.objects.create(worker=editor, date=date(2026, 12, 1), kind="free")
        Day.objects.create(worker=buyer, date=date(2026, 12, 1), kind="free")

        with patch("tim.slack_reminders.send_dm") as send:
            with patch("tim.slack_reminders.timezone.now", return_value=self.friday_afternoon):
                self.assertEqual(self.scheduler.post(self.endpoint).status_code, 204)
                self.assertEqual(self.scheduler.post(self.endpoint).status_code, 204)
            summaries = {call.kwargs["recipient"]: call.args[0] for call in send.call_args_list}
            self.assertEqual(send.call_count, 3)
            self.assertEqual(set(summaries), {"UOWNER1", "ULEAD1", "UWORKER1"})
            self.assertIn("Video editor", summaries["UOWNER1"])
            self.assertIn("Media buyer", summaries["UOWNER1"])
            self.assertIn("Video editor", summaries["UWORKER1"])
            self.assertIn("Media buyer", summaries["UWORKER1"])
            self.assertIn("Video editor", summaries["ULEAD1"])
            self.assertNotIn("Media buyer", summaries["ULEAD1"])

            buyer_role.approvers.add(editor_lead)
            send.reset_mock()
            with patch("tim.slack_reminders.timezone.now", return_value=datetime(2026, 11, 30, 16, 5, tzinfo=timezone.utc)):
                self.assertEqual(self.scheduler.post(self.endpoint).status_code, 204)
            summaries = {call.kwargs["recipient"]: call.args[0] for call in send.call_args_list}
            self.assertIn("Video editor", summaries["ULEAD1"])
            self.assertIn("Media buyer", summaries["ULEAD1"])

    def test_paused_linked_legacy_account_does_not_receive_a_fallback(self):
        owner = User.objects.create_user("owner", is_staff=True)
        SlackSubscription.objects.create(user=owner, member_id="UOWNER1", enabled=False)
        self.add_day("ana", "free")
        with patch("tim.slack_reminders.timezone.now", return_value=self.friday_afternoon):
            self.assertEqual(self.scheduler.post(self.endpoint).status_code, 204)
        self.slack.assert_not_called()

    def test_delivery_retries_only_the_recipient_that_failed(self):
        admin = User.objects.create_user("second-admin", is_staff=True)
        SlackSubscription.objects.create(user=admin, member_id="UADMIN2")
        self.add_day("ana", "free")
        with patch("tim.slack_reminders.timezone.now", return_value=self.friday_afternoon), patch(
            "tim.slack_reminders.send_dm", side_effect=[SlackDeliveryError("Unavailable"), None],
        ) as send:
            with self.assertLogs("tim.slack_reminders", level="WARNING"):
                self.assertEqual(self.scheduler.post(self.endpoint).status_code, 502)
            self.assertEqual(set(SlackReminderDelivery.objects.values_list("recipient_id", flat=True)), {"UOWNER1"})
            send.reset_mock(side_effect=True)
            self.assertEqual(self.scheduler.post(self.endpoint).status_code, 204)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.kwargs["recipient"], "UADMIN2")
