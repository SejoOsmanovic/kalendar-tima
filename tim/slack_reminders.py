import logging
import re
from datetime import timedelta
from html import escape

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.dateformat import format as format_date
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Day, SlackReminderDelivery

logger = logging.getLogger(__name__)

CROWDED_SAMPLE_NAMES = (
    "Ari Linden",
    "Casey Vale",
    "Dana Mercer",
    "Emery Reed",
    "Finley Wells",
    "Harper Bell",
    "Jules Rowan",
    "Kai Banks",
    "Mika Lane",
    "Noa Ellis",
    "Quinn Brooks",
    "Riley Hart",
)


class SlackDeliveryError(Exception):
    pass


def call_slack(method, payload):
    try:
        response = requests.post(
            f"https://slack.com/api/{method}",
            headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            json=payload,
            timeout=(3, 6),
            allow_redirects=False,
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError):
        raise SlackDeliveryError(f"{method} did not return a usable response") from None

    if not isinstance(result, dict):
        raise SlackDeliveryError(f"{method} returned an unexpected response")
    if result.get("ok") is not True:
        error = result.get("error")
        code = error if isinstance(error, str) and re.fullmatch(r"[a-z0-9_]{1,64}", error) else "unknown_error"
        raise SlackDeliveryError(f"{method} returned {code}")
    return result


def send_dm(message):
    recipient = settings.SLACK_RECIPIENT_ID
    result = call_slack("conversations.open", {"users": recipient, "return_im": True})
    channel = result.get("channel")
    if not isinstance(channel, dict) or channel.get("is_im") is not True or channel.get("user") != recipient:
        raise SlackDeliveryError("Slack did not confirm a private DM with the configured member")
    channel_id = channel.get("id")
    if not isinstance(channel_id, str) or not re.fullmatch(r"D[A-Z0-9]+", channel_id):
        raise SlackDeliveryError("Slack did not return a valid direct conversation ID")

    call_slack("chat.postMessage", {
        "channel": channel_id,
        "text": message,
        "mrkdwn": False,
        "unfurl_links": False,
        "unfurl_media": False,
    })


def next_workday(day):
    target = day + timedelta(days=1)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    return target


def format_reminder(target, names):
    return "\n".join([
        f"Days off on {format_date(target, 'l, F j, Y')}",
        *(f"• {escape(' '.join(name.split()), quote=False)}" for name in names),
    ])


def send_next_workday_reminder(request):
    now = timezone.localtime()
    # A delayed workflow must not send a weekend or next-morning reminder.
    if now.weekday() >= 5 or now.hour < 17:
        return

    target = next_workday(now.date())
    entries = (
        Day.objects.filter(date=target, kind__in=("free", "vacation"), worker__is_active=True)
        .filter(Q(source__isnull=True) | Q(source__status="approved"))
        .select_related("worker")
        .order_by("worker__first_name", "worker__last_name", "worker__username")
    )
    names = [row.worker.get_full_name() or row.worker.username for row in entries]
    if not names:
        return

    calendar_url = request.build_absolute_uri(reverse("calendar", query={"dan": target.isoformat()}))
    message = f"{format_reminder(target, names)}\n\nOpen the team calendar {calendar_url}"
    with transaction.atomic():
        # Concurrent requests wait on the unique date. A failed Slack call rolls back the claim.
        _, created = SlackReminderDelivery.objects.get_or_create(absence_date=target)
        if created:
            send_dm(message)


@csrf_exempt
@require_POST
@never_cache
def reminder(request, sample=None):
    key = settings.SLACK_REMINDER_KEY
    if not key or not constant_time_compare(request.headers.get("Authorization", ""), f"Bearer {key}"):
        return HttpResponse(status=403)
    if not settings.SLACK_BOT_TOKEN or not re.fullmatch(r"[UW][A-Z0-9]+", settings.SLACK_RECIPIENT_ID):
        return HttpResponse(status=409)

    try:
        if sample:
            names = CROWDED_SAMPLE_NAMES if sample == "group" else ("Sample team member",)
            message = format_reminder(next_workday(timezone.localdate()), names)
            send_dm(f"TEST · {message}\n\nFictional team data from Scale Up Vacation Tracker.")
        else:
            send_next_workday_reminder(request)
    except SlackDeliveryError as exc:
        logger.warning("Slack reminder delivery failed. %s", exc)
        return HttpResponse(status=502)
    return HttpResponse(status=204)
