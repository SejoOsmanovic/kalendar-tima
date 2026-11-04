from calendar import Calendar
from collections import defaultdict
from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import Ask, Entry, Member, Registration, RoleSelection, ApprovalScope, DateSettings
from .models import Day, KINDS, LeaveRequest, PendingRegistration, JobRole, MemberRole, EntryType, DatePreference

MONTHS = "January February March April May June July August September October November December".split()


def reviewable_requests(user):
    if user.is_staff:
        return LeaveRequest.objects.all()
    if not user.approval_roles.exists():
        return None
    return LeaveRequest.objects.filter(worker__job__role__approvers=user).exclude(worker=user)


def date_style(user):
    return getattr(getattr(user, "date_preference", None), "style", "us")


@login_required
def preferences(request):
    form = DateSettings(request.POST if request.method == "POST" else None, initial={"style": date_style(request.user)})
    if request.method == "POST" and form.is_valid():
        DatePreference.objects.update_or_create(user=request.user, defaults={"style": form.cleaned_data["style"]})
        messages.success(request, "Your date format has been saved.")
        return redirect("calendar")
    return render(request, "form.html", {"title": "My preferences", "button": "Save preferences", "form": form})


def badge(request):
    if not request.user.is_authenticated:
        return {"google_client_id": settings.GOOGLE_CLIENT_ID,
                "google_return_url": request.build_absolute_uri(reverse("google_return")) if settings.GOOGLE_REDIRECT_ENABLED else ""}
    context = {"date_format": "d.m.Y." if date_style(request.user) == "eu" else "m/d/Y",
               "decisions": LeaveRequest.objects.filter(worker=request.user, decision_seen=False,
               status__in=["approved", "rejected"]).order_by("-decided")}
    requests = reviewable_requests(request.user)
    if requests is not None:
        context["can_review"] = True
        context["pending"] = requests.filter(status="pending").count()
    if request.user.is_staff:
        context["pending_registrations"] = PendingRegistration.objects.count()
    return context


@login_required
@require_POST
def acknowledge(request, pk):
    LeaveRequest.objects.filter(pk=pk, worker=request.user, status__in=["approved", "rejected"]).update(decision_seen=True)
    return redirect("mine")


def admin(view):
    @login_required
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return guarded


def name(user):
    return user.get_full_name() or user.username


@login_required
def calendar_view(request):
    today = timezone.localdate()
    try:
        selected = date.fromisoformat(request.GET.get("dan", today.isoformat()))
        if not 2 <= selected.year <= 9998:
            raise ValueError
        person = int(request.GET.get("osoba") or 0)
        role = int(request.GET.get("rola") or 0)
    except (ValueError, OverflowError):
        return HttpResponseBadRequest("Invalid date or filter.")
    dates = list(Calendar().itermonthdates(selected.year, selected.month))
    rows = Day.objects.filter(date__range=(dates[0], dates[-1])).select_related("worker__job__role", "entry_type").order_by("worker__first_name", "worker__username")
    if person:
        rows = rows.filter(worker_id=person)
    if role:
        rows = rows.filter(worker__job__role_id=role)
    days = defaultdict(list)
    for row in rows:
        days[row.date].append(row)
    cells = [{"date": d, "kinds": sorted({(row.badge_class, row.label) for row in days[d]})} for d in dates]
    first = selected.replace(day=1)
    return render(request, "calendar.html", {"selected": selected, "today": today, "month": MONTHS[selected.month-1],
        "prev": (first-timedelta(days=1)).replace(day=1), "next": (first+timedelta(days=32)).replace(day=1),
        "people": User.objects.filter(pending_registration__isnull=True).order_by("first_name","username"), "person": person, "cells": cells,
        "roles": JobRole.objects.all(), "role": role, "rows": days[selected],
        "legend": KINDS + [(t.badge_class, t.name) for t in EntryType.objects.all()]})


def insert_days(workers, start, end, kind, source=None, holiday_name="", entry_type_id=None):
    Day.objects.bulk_create([Day(worker=w, date=start+timedelta(days=i), kind=kind, source=source, holiday_name=holiday_name, entry_type_id=entry_type_id)
        for w in workers for i in range((end-start).days+1)], batch_size=1000)


@login_required
def ask(request):
    form = Ask(request.POST if request.method == "POST" else None, date_style=date_style(request.user), initial={"start": request.GET.get("datum", "")})
    if request.method == "POST" and form.is_valid():
        LeaveRequest.objects.create(worker=request.user, **form.cleaned_data)
        messages.success(request, "Your request has been submitted.")
        return redirect("mine")
    return render(request, "form.html", {"form": form, "title": "Request time off", "button": "Submit request"})


@admin
@require_POST
def type_color(request, pk):
    color = request.POST.get("color")
    if color not in dict(JobRole.COLORS):
        return HttpResponseBadRequest("Choose one of the available colors.")
    entry_type = get_object_or_404(EntryType, pk=pk)
    entry_type.color = color
    entry_type.save(update_fields=["color"])
    messages.success(request, f"Color saved for {entry_type.name}.")
    return redirect(reverse("entry", query={"datum": request.POST.get("datum", ""), "vrsta": f"custom-{pk}"}))


@admin
def entry(request):
    if request.method == "POST" and request.POST.get("action") == "add_type":
        label = request.POST.get("name", "").strip()
        color = request.POST.get("color", "purple")
        if color not in dict(JobRole.COLORS):
            messages.error(request, "Choose a color from the list.")
        elif not label or len(label) > 60:
            messages.error(request, "Enter a type name of up to 60 characters.")
        elif label.casefold() in {text.casefold() for _, text in KINDS}:
            messages.error(request, "An entry type with this name already exists.")
        else:
            try:
                with transaction.atomic():
                    entry_type = EntryType.objects.create(name=label, color=color)
            except IntegrityError:
                messages.error(request, "An entry type with this name already exists.")
            else:
                messages.success(request, "The new type is selected for this entry.")
                return redirect(reverse("entry", query={"datum": request.GET.get("datum", ""), "vrsta": f"custom-{entry_type.pk}"}))
        return redirect(reverse("entry", query={"datum": request.GET.get("datum", "")}))
    form = Entry(request.POST if request.method == "POST" else None, date_style=date_style(request.user),
                 initial={"start": request.GET.get("datum", ""), "kind": request.GET.get("vrsta", "free")})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                workers = User.objects.filter(is_active=True) if data["scope"] == "all" else data["workers"]
                kind, _, type_id = data["kind"].partition("-")
                insert_days(workers.order_by("pk"), data["start"], data["end"], kind, entry_type_id=type_id or None,
                            holiday_name=data["holiday_name"] if data["kind"] == "holiday" else "")
        except IntegrityError:
            form.add_error(None, "A selected member already has an absence on one of these dates. No entries were saved.")
        else:
            messages.success(request, "Entry saved.")
            return redirect("/?dan="+data["start"].isoformat())
    return render(request, "form.html", {"form": form, "colors": JobRole.COLORS, "entry_types": EntryType.objects.all(),
                                         "title": "New calendar entry", "button": "Save entry"})


@login_required
def mine(request):
    return render(request, "requests.html", {"items": LeaveRequest.objects.filter(worker=request.user).select_related("reviewer").order_by("-pk")})


@login_required
@require_POST
def withdraw(request, pk):
    changed = LeaveRequest.objects.filter(pk=pk, worker=request.user, status="pending").update(status="withdrawn")
    messages.info(request, "Request withdrawn." if changed else "This request cannot be withdrawn.")
    return redirect("mine")


@login_required
def queue(request):
    requests = reviewable_requests(request.user)
    if requests is None:
        raise PermissionDenied
    items = requests.select_related("worker", "reviewer").order_by("-pk")
    for item in items:
        if item.status == "pending":
            item.overlap = Day.objects.filter(date__range=(item.start, item.end)).exclude(worker=item.worker).select_related("worker").order_by("date","worker__first_name")
    return render(request, "requests.html", {"items": sorted(items, key=lambda r: r.status != "pending"), "review": True})


@login_required
@require_POST
def decide(request, pk):
    requests = reviewable_requests(request.user)
    if requests is None:
        raise PermissionDenied
    get_object_or_404(requests.only("pk"), pk=pk)
    choice = request.POST.get("choice")
    comment = request.POST.get("comment", "").strip()
    if choice not in ("approved","rejected") or len(comment)>2000:
        return HttpResponseBadRequest("Invalid decision or comment.")
    try:
        with transaction.atomic():
            changed = requests.filter(pk=pk, status="pending").update(status=choice, reviewer=request.user, decided=timezone.now(), comment=comment)
            if not changed:
                messages.info(request, "This request has already been reviewed or withdrawn.")
            else:
                if choice == "approved":
                    item = LeaveRequest.objects.select_related("worker").get(pk=pk)
                    insert_days([item.worker], item.start, item.end, item.kind, item)
                messages.success(request, "Decision saved.")
    except IntegrityError:
        messages.error(request, "This member already has time off during this period. The request is still pending.")
    return redirect("queue")


@admin
def registration_count(request):
    return JsonResponse({"count": PendingRegistration.objects.count()}, headers={"Cache-Control": "private, no-store"})


@admin
def team(request):
    form = Member(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            with transaction.atomic():
                user = User.objects.create_user(d["username"], password=d["password"], first_name=d["name"], is_staff=d["role"]=="admin")
                MemberRole.objects.create(user=user, role=d["job_role"])
        except IntegrityError:
            form.add_error("username", "This username is already in use.")
        else:
            messages.success(request, "Account created.")
            return redirect("team")
    return render(request, "team.html", {"form": form, "roles": JobRole.objects.all(), "colors": JobRole.COLORS,
        "registrations": PendingRegistration.objects.select_related("user__job__role").order_by("pk"),
        "members": User.objects.filter(pending_registration__isnull=True).select_related("job__role").prefetch_related("approval_roles").order_by("-is_active","first_name","username")})


@admin
@require_POST
def approval_scope(request, pk):
    if pk == request.user.pk:
        raise PermissionDenied
    form = ApprovalScope(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Select valid job roles.")
    with transaction.atomic():
        member = get_object_or_404(User.objects.select_for_update(), pk=pk, is_active=True, is_superuser=False)
        member.approval_roles.set(form.cleaned_data["roles"])
        if member.is_staff:
            member.is_staff = False
            member.save(update_fields=["is_staff"])
    messages.success(request, "Approval permissions saved.")
    return redirect("team")


@admin
@require_POST
def role_color(request, pk):
    color = request.POST.get("color")
    if color not in dict(JobRole.COLORS):
        return HttpResponseBadRequest("Choose one of the available colors.")
    role = get_object_or_404(JobRole, pk=pk)
    role.color = color
    role.save(update_fields=["color"])
    messages.success(request, f"Color saved for {role.name}.")
    return redirect("team")


@admin
@require_POST
def add_role(request):
    name = request.POST.get("name", "").strip()
    color = request.POST.get("color", "")
    if not name or len(name) > 60 or color not in dict(JobRole.COLORS):
        messages.error(request, "Enter a role name of up to 60 characters and choose a color.")
    else:
        try:
            with transaction.atomic():
                JobRole.objects.create(name=name, color=color)
        except IntegrityError:
            messages.error(request, "A role with this name already exists.")
        else:
            messages.success(request, "Job role added.")
    return redirect("team")


@admin
@require_POST
def assign_role(request, pk):
    member = get_object_or_404(User, pk=pk, is_active=True)
    form = RoleSelection(request.POST)
    if form.is_valid():
        MemberRole.objects.update_or_create(user=member, defaults={"role": form.cleaned_data["job_role"]})
        messages.success(request, "Job role saved.")
    else:
        messages.error(request, "Select an existing job role.")
    return redirect("team")


def register(request):
    if request.user.is_authenticated:
        return redirect("calendar")
    form = Registration(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                user = User.objects.create_user(username=data["email"], email=data["email"], first_name=data["name"],
                                                password=data["password"], is_active=False)
                PendingRegistration.objects.create(user=user)
                MemberRole.objects.create(user=user, role=data["job_role"])
        except IntegrityError:
            form.add_error("email", "This email address is already in use.")
        else:
            messages.success(request, "Registration submitted. Once an administrator approves your account, sign in with your email and password.")
            return redirect("login")
    return render(request, "form.html", {"form": form, "title": "Register", "button": "Request access"})


@admin
@require_POST
def approve_member(request, pk):
    with transaction.atomic():
        removed, _ = PendingRegistration.objects.filter(user_id=pk).delete()
        if removed:
            User.objects.filter(pk=pk).update(is_active=True)
    messages.info(request, "Access approved." if removed else "This registration is no longer pending.")
    return redirect("team")


@admin
@require_POST
def promote(request, pk):
    changed = User.objects.filter(pk=pk, is_active=True, is_staff=False).update(is_staff=True)
    messages.info(request, "Administrator access granted." if changed else "Access level unchanged.")
    return redirect("team")


@admin
@require_POST
def archive(request, pk):
    if pk == request.user.pk:
        messages.error(request, "You cannot archive your own account.")
    else:
        with transaction.atomic():
            member = get_object_or_404(User.objects.select_for_update(), pk=pk)
            member.is_active = False
            member.save(update_fields=["is_active"])
            LeaveRequest.objects.filter(worker=member,status="pending").update(status="withdrawn")
        messages.success(request, "Account archived.")
    return redirect("team")
