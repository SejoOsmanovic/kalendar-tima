from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from .balances import balances
from .forms import Ask
from .models import AnnualAllowance, Day, JobRole, LeaveRequest, MemberRole


class AnnualBalanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("owner", is_staff=True)
        self.worker = User.objects.create_user("member")
        self.allowance = AnnualAllowance.objects.create(worker=self.worker, year=2026, days_off=5, sick_days=5, holidays=2)

    @patch("tim.balances.timezone.localdate", return_value=date(2026, 11, 24))
    def test_weekdays_legacy_vacation_and_separate_categories(self, today):
        for day, kind in [(20, "free"), (21, "free"), (22, "vacation"), (23, "vacation"), (25, "free"), (26, "sick"), (27, "holiday")]:
            Day.objects.create(worker=self.worker, date=date(2026, 11, day), kind=kind)
        Day.objects.create(worker=self.worker, date=date(2027, 1, 4), kind="free")
        rows = balances(self.worker, 2026)
        self.assertEqual((rows[0]["used"], rows[0]["reserved"], rows[0]["remaining"]), (2, 1, 2))
        self.assertEqual(rows[1]["remaining"], 4)
        self.assertEqual(rows[2]["remaining"], 1)
        self.assertIsNone(balances(self.worker, 2027)[0]["remaining"])
        self.client.force_login(self.worker)
        self.assertContains(self.client.get("/balances/?year=2026"), "Weekend · not counted")

    def test_permissions_validation_and_year_isolation(self):
        url = f"/tim/{self.worker.pk}/balances/?year=2026"
        self.client.force_login(self.worker)
        self.assertEqual(self.client.post(url, {"year":2026,"days_off":99,"sick_days":99,"holidays":99}).status_code, 403)
        self.assertEqual(self.client.get(f"/tim/{self.admin.pk}/balances/").status_code, 403)
        role = JobRole.objects.first()
        MemberRole.objects.create(user=self.worker, role=role)
        approver = User.objects.create_user("approver")
        role.approvers.add(approver)
        self.client.force_login(approver)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(url, {"year":2026,"days_off":-1,"sick_days":5,"holidays":2})
        self.allowance.refresh_from_db()
        self.assertEqual(self.allowance.days_off, 5)
        self.client.post(url, {"year":2027,"days_off":10,"sick_days":6,"holidays":8})
        self.assertEqual(AnnualAllowance.objects.get(worker=self.worker, year=2027).days_off, 10)
        self.assertEqual(self.client.get("/balances/?year=invalid").status_code, 400)

    def test_cross_year_request_and_withdrawal(self):
        self.client.force_login(self.worker)
        self.client.post("/trazi/", {"kind":"free", "start":"12/31/2026", "end":"01/04/2027"})
        item = LeaveRequest.objects.get(worker=self.worker)
        self.client.post(f"/moji/{item.pk}/povuci/")
        self.assertEqual(balances(self.worker,2026)[0]["remaining"],5)
        self.client.post("/trazi/", {"kind":"free", "start":"12/31/2026", "end":"01/04/2027"})
        item = LeaveRequest.objects.latest("pk")
        AnnualAllowance.objects.create(worker=self.worker, year=2027, days_off=1)
        self.client.force_login(self.admin)
        self.client.post(f"/zahtjevi/{item.pk}/odluka/", {"choice":"approved"})
        self.assertEqual(balances(self.worker,2026)[0]["remaining"],4)
        self.assertEqual(balances(self.worker,2027)[0]["remaining"],-1)

    def test_existing_custom_sick_days_keep_their_color_and_count(self):
        from importlib import import_module
        from django.apps import apps
        from .models import EntryType
        entry_type = EntryType.objects.create(name="Sick days", color="pink")
        day = Day.objects.create(worker=self.worker, date=date(2026,11,24), kind="custom", entry_type=entry_type)
        import_module("tim.migrations.0017_classify_existing_sick_days").classify_sick_days(apps, None)
        day.refresh_from_db()
        self.assertEqual(day.kind, "sick")
        self.assertEqual(day.badge_class, "custom role-pink")
        self.assertEqual(balances(self.worker,2026)[1]["remaining"],4)

    def test_decisions_manual_entries_and_reversal_drive_balance(self):
        self.client.force_login(self.admin)
        item = LeaveRequest.objects.create(worker=self.worker, start=date(2026,11,20), end=date(2026,11,23), kind="free")
        decide = f"/zahtjevi/{item.pk}/odluka/"
        self.assertEqual(balances(self.worker,2026)[0]["remaining"],5)
        self.client.post(decide, {"choice":"approved"})
        self.assertEqual(balances(self.worker,2026)[0]["remaining"],3)
        self.client.post(decide, {"choice":"approved"})
        self.assertEqual(balances(self.worker,2026)[0]["remaining"],3)
        self.client.post(f"/zahtjevi/{item.pk}/undo/", {"revision":"0"})
        self.assertEqual(balances(self.worker,2026)[0]["remaining"],5)
        self.client.post(decide, {"choice":"rejected","revision":"1"})
        self.assertEqual(balances(self.worker,2026)[0]["remaining"],5)
        self.client.post("/unos/", {"kind":"sick","start":"11/24/2026","scope":"selected","workers":[self.worker.pk]})
        self.assertEqual(balances(self.worker,2026)[1]["remaining"],4)
        item = LeaveRequest.objects.create(worker=self.worker, start=date(2026,11,25), end=date(2026,11,25), kind="sick")
        self.client.post(f"/zahtjevi/{item.pk}/odluka/", {"choice":"approved"})
        self.assertEqual(balances(self.worker,2026)[1]["remaining"],3)
        self.client.post(f"/zahtjevi/{item.pk}/delete/", {"status":"approved","revision":"0"})
        self.assertEqual(balances(self.worker,2026)[1]["remaining"],4)
        self.assertEqual(list(Ask().fields["kind"].choices), [("free","Days off"),("sick","Sick days")])
