import logging
from datetime import timedelta
from secrets import randbelow

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import SlackLinkChallenge, SlackSubscription
from .slack_reminders import SLACK_MEMBER_ID_PATTERN, SlackDeliveryError, send_dm

logger = logging.getLogger(__name__)
CODE_TTL = timedelta(minutes=10)
RESEND_INTERVAL = timedelta(minutes=1)
MAX_ATTEMPTS = 5


class SlackMemberForm(forms.Form):
    member_id = forms.RegexField(
        regex=SLACK_MEMBER_ID_PATTERN,
        label="Slack member ID",
        max_length=32,
        help_text="In Slack, open your profile and choose More → Copy member ID.",
    )


class SlackCodeForm(forms.Form):
    code = forms.RegexField(
        regex=r"^[0-9]{8}$",
        label="Verification code",
        max_length=8,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}),
        error_messages={"invalid": "Enter the 8-digit code from Slack."},
    )


def code_digest(user, member_id, code):
    return salted_hmac(
        "tracker-slack-link", f"{user.pk}:{member_id}:{code}", algorithm="sha256",
    ).hexdigest()


def start_link(user, member_id):
    if SlackSubscription.objects.filter(member_id=member_id).exists():
        return "This Slack account is already connected."

    now = timezone.now()
    code = f"{randbelow(100_000_000):08d}"
    fields = {"member_id": member_id, "code_digest": code_digest(user, member_id, code), "sent_at": now, "attempts": 0}
    with transaction.atomic():
        challenge, created = SlackLinkChallenge.objects.select_for_update().get_or_create(user=user, defaults=fields)
        if not created:
            if now < challenge.sent_at + RESEND_INTERVAL:
                return "Wait one minute before requesting another code."
            for name, value in fields.items():
                setattr(challenge, name, value)
            challenge.save(update_fields=fields.keys())

    try:
        send_dm(
            f"Your Scale Up Vacation Tracker verification code is {code}. "
            "Enter it in Slack reminders within 10 minutes to connect your account.",
            recipient=member_id,
        )
    except SlackDeliveryError as exc:
        logger.warning("Slack verification code delivery failed. %s", exc)
        return "Slack could not deliver the code. Check your member ID and try again in a minute."
    return None


@transaction.atomic
def finish_link(user, code):
    challenge = SlackLinkChallenge.objects.select_for_update().filter(user=user).first()
    if not challenge or challenge.attempts >= MAX_ATTEMPTS or timezone.now() >= challenge.sent_at + CODE_TTL:
        return "Request a new verification code."

    if not constant_time_compare(code_digest(user, challenge.member_id, code), challenge.code_digest):
        challenge.attempts += 1
        challenge.save(update_fields=["attempts"])
        return "That code does not match. Check your Slack message."

    try:
        with transaction.atomic():
            SlackSubscription.objects.create(
                user=user,
                member_id=challenge.member_id,
                team_overview=not user.is_staff and not user.approval_roles.exists(),
            )
    except IntegrityError:
        return "This Slack account is already connected."
    challenge.delete()
    return None


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def preferences(request):
    user = request.user
    roles = [] if user.is_staff else list(user.approval_roles.values_list("name", flat=True))
    if not user.is_active:
        raise PermissionDenied

    configured = bool(settings.SLACK_BOT_TOKEN and settings.SLACK_REMINDER_KEY)
    subscription = SlackSubscription.objects.filter(user=user).first()
    member_form = SlackMemberForm()
    code_form = SlackCodeForm()
    if request.method == "POST":
        if not configured:
            return HttpResponseBadRequest("Slack reminders are unavailable.")
        action = request.POST.get("action")
        if subscription:
            if action not in ("enable", "disable"):
                return HttpResponseBadRequest("Choose whether to receive Slack reminders.")
            subscription.enabled = action == "enable"
            if subscription.enabled and not user.is_staff and not roles:
                subscription.team_overview = True
            subscription.save(update_fields=["enabled", "team_overview"])
            messages.success(request, "Slack reminders turned on." if subscription.enabled else "Slack reminders paused.")
            return redirect("slack_preferences")
        if action == "send_code":
            member_form = SlackMemberForm(request.POST)
            if member_form.is_valid():
                error = start_link(user, member_form.cleaned_data["member_id"])
                if error:
                    member_form.add_error("member_id", error)
                else:
                    messages.success(request, "Verification code sent to your Slack DM.")
                    return redirect("slack_preferences")
        elif action == "verify_code":
            code_form = SlackCodeForm(request.POST)
            if code_form.is_valid():
                error = finish_link(user, code_form.cleaned_data["code"])
                if error:
                    code_form.add_error("code", error)
                else:
                    messages.success(request, "Slack connected. Days off reminders are on.")
                    return redirect("slack_preferences")
        else:
            return HttpResponseBadRequest("Choose a Slack setup action.")

    waiting_for_code = SlackLinkChallenge.objects.filter(
        user=user, attempts__lt=MAX_ATTEMPTS, sent_at__gt=timezone.now() - CODE_TTL,
    ).exists()
    return render(request, "slack_preferences.html", {
        "configured": configured,
        "subscription": subscription,
        "receiving_reminders": bool(
            subscription and subscription.enabled and (user.is_staff or roles or subscription.team_overview)
        ),
        "roles": roles,
        "member_form": member_form,
        "code_form": code_form,
        "waiting_for_code": waiting_for_code,
    })
