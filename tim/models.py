from django.contrib.auth.models import User
from django.db import models

LEAVE = [("free", "Days off"), ("sick", "Sick days")]
KINDS = LEAVE + [("holiday", "Holiday"), ("closed", "Company closure")]
STATES = [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Declined"), ("withdrawn", "Withdrawn")]


class DatePreference(models.Model):
    FORMATS = [("us", "Month first (MM/DD/YYYY)"), ("eu", "Day first (DD.MM.YYYY.)")]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="date_preference")
    style = models.CharField(max_length=2, choices=FORMATS, default="us")


class GoogleIdentity(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    subject = models.CharField(max_length=255, unique=True)


class PendingRegistration(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="pending_registration")


class JobRole(models.Model):
    approvers = models.ManyToManyField(User, blank=True, related_name="approval_roles")
    COLORS = [("purple", "Purple"), ("blue", "Blue"), ("green", "Green"),
              ("amber", "Yellow"), ("pink", "Pink"), ("teal", "Teal")]
    name = models.CharField(max_length=60)
    color = models.CharField(max_length=10, choices=COLORS)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(models.functions.Lower("name"), name="unique_job_role_name")]

    def __str__(self):
        return self.name


class MemberRole(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="job")
    role = models.ForeignKey(JobRole, on_delete=models.PROTECT)


class LeaveRequest(models.Model):
    is_paid = models.BooleanField(null=True)
    worker = models.ForeignKey(User, on_delete=models.PROTECT)
    start = models.DateField()
    end = models.DateField()
    kind = models.CharField(max_length=12, choices=LEAVE + [("vacation", "Days off")])
    note = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATES, default="pending")
    comment = models.TextField(blank=True)
    reviewer = models.ForeignKey(User, null=True, related_name="decisions", on_delete=models.PROTECT)
    decided = models.DateTimeField(null=True)
    decision_seen = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=0)


class ReversedDecision(models.Model):
    is_paid = models.BooleanField(null=True)
    request = models.ForeignKey(LeaveRequest, related_name="reversed_decisions", on_delete=models.CASCADE)
    status = models.CharField(max_length=12, choices=STATES)
    reviewer = models.ForeignKey(User, related_name="+", on_delete=models.PROTECT)
    decided = models.DateTimeField()
    comment = models.TextField(blank=True)
    reversed_by = models.ForeignKey(User, related_name="+", on_delete=models.PROTECT)
    reversed_at = models.DateTimeField(auto_now_add=True)


class EntryType(models.Model):
    color = models.CharField(max_length=10, choices=JobRole.COLORS, default="purple")

    @property
    def badge_class(self):
        return f"custom role-{self.color}"

    name = models.CharField(max_length=60)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(models.functions.Lower("name"), name="unique_entry_type_name")]


class Day(models.Model):
    is_paid = models.BooleanField(null=True)
    worker = models.ForeignKey(User, on_delete=models.PROTECT)
    date = models.DateField(db_index=True)
    kind = models.CharField(max_length=12, choices=KINDS + [("vacation", "Days off"), ("custom", "Custom entry")])
    entry_type = models.ForeignKey(EntryType, null=True, blank=True, on_delete=models.PROTECT)
    holiday_name = models.CharField(max_length=100, blank=True, default="")
    source = models.ForeignKey(LeaveRequest, null=True, on_delete=models.PROTECT)

    @property
    def badge_class(self):
        if self.kind == "vacation":
            return "free"
        return self.entry_type.badge_class if self.entry_type_id else self.kind

    @property
    def label(self):
        if self.entry_type_id:
            return self.entry_type.name
        if self.kind == "holiday" and self.holiday_name:
            return f"Holiday ({self.holiday_name})"
        return self.get_kind_display()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["worker", "date"], name="one_absence_per_day")]


class AnnualAllowance(models.Model):
    worker = models.ForeignKey(User, on_delete=models.CASCADE)
    year = models.PositiveIntegerField()
    days_off = models.PositiveIntegerField(default=5)
    sick_days = models.PositiveIntegerField(default=5)
    holidays = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["worker", "year"], name="one_allowance_per_year")]


class SlackReminderDelivery(models.Model):
    absence_date = models.DateField()
    recipient_id = models.CharField(max_length=32, blank=True, default="")
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["absence_date", "recipient_id"], name="one_slack_reminder_per_recipient")
        ]


class SlackSubscription(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    member_id = models.CharField(max_length=32, unique=True)
    enabled = models.BooleanField(default=True)


class SlackLinkChallenge(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    member_id = models.CharField(max_length=32)
    code_digest = models.CharField(max_length=64)
    sent_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
