from datetime import date

from django.utils import timezone

from .models import AnnualAllowance, Day


def balances(worker, year):
    """Derive balances from calendar days so undo/delete cannot leave stale totals."""
    allowance = AnnualAllowance.objects.filter(worker=worker, year=year).first()
    categories = {
        "free": {"label": "Days off", "field": "days_off", "used": 0, "reserved": 0},
        "sick": {"label": "Sick days", "field": "sick_days", "used": 0, "reserved": 0},
        "holiday": {"label": "Holidays", "field": "holidays", "used": 0, "reserved": 0},
    }
    today = timezone.localdate()
    for day in Day.objects.filter(worker=worker, date__range=(date(year, 1, 1), date(year, 12, 31))):
        kind = "free" if day.kind == "vacation" else day.kind
        if kind in categories and day.date.weekday() < 5:
            categories[kind]["used" if day.date <= today else "reserved"] += 1
    for row in categories.values():
        row["total"] = getattr(allowance, row["field"]) if allowance else None
        row["remaining"] = row["total"] - row["used"] - row["reserved"] if allowance else None
    return list(categories.values())
