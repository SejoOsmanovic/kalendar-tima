from django.contrib.auth.models import User
from django.db import models

LEAVE = [("free", "Day off"), ("vacation", "Vacation")]
KINDS = LEAVE + [("holiday", "Holiday"), ("closed", "Company closure")]
STATES = [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Declined"), ("withdrawn", "Withdrawn")]


class PendingRegistration(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="pending_registration")


class JobRole(models.Model):
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
    worker = models.ForeignKey(User, on_delete=models.PROTECT)
    start = models.DateField()
    end = models.DateField()
    kind = models.CharField(max_length=12, choices=LEAVE)
    note = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATES, default="pending")
    comment = models.TextField(blank=True)
    reviewer = models.ForeignKey(User, null=True, related_name="decisions", on_delete=models.PROTECT)
    decided = models.DateTimeField(null=True)
    decision_seen = models.BooleanField(default=False)


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
    worker = models.ForeignKey(User, on_delete=models.PROTECT)
    date = models.DateField(db_index=True)
    kind = models.CharField(max_length=12, choices=KINDS + [("custom", "Custom entry")])
    entry_type = models.ForeignKey(EntryType, null=True, blank=True, on_delete=models.PROTECT)
    holiday_name = models.CharField(max_length=100, blank=True, default="")
    source = models.ForeignKey(LeaveRequest, null=True, on_delete=models.PROTECT)

    @property
    def badge_class(self):
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
