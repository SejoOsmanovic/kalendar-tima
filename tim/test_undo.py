from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from .models import Day, JobRole, LeaveRequest, MemberRole


class UndoDecisionTest(TestCase):
    def test_only_full_admin_can_reverse_and_correct_decisions(self):
        worker = User.objects.create_user("worker")
        approver = User.objects.create_user("approver")
        admin = User.objects.create_user("admin", is_staff=True)
        role = JobRole.objects.first()
        MemberRole.objects.create(user=worker, role=role)
        role.approvers.add(approver)
        day = date(2027, 3, 4)
        item = LeaveRequest.objects.create(worker=worker, start=day, end=day, kind="free")
        unrelated = Day.objects.create(worker=approver, date=day, kind="vacation")
        decide = f"/zahtjevi/{item.pk}/odluka/"
        undo = f"/zahtjevi/{item.pk}/undo/"
        self.client.force_login(approver)
        self.client.post(decide, {"choice":"approved", "comment":"First decision", "is_paid":"on"})
        self.assertTrue(Day.objects.get(source=item).is_paid)
        self.assertNotContains(self.client.get("/zahtjevi/"), "Undo decision")
        for user in (approver, worker):
            self.client.force_login(user)
            self.assertEqual(self.client.post(undo, {"revision":"0"}).status_code, 403)
        self.client.force_login(admin)
        self.assertContains(self.client.get("/zahtjevi/"), "Undo decision")
        self.client.post(undo, {"revision":"0"})
        self.assertFalse(Day.objects.filter(source=item).exists())
        self.assertTrue(Day.objects.filter(pk=unrelated.pk).exists())
        self.client.post(decide, {"revision":"0", "choice":"approved"})
        item.refresh_from_db()
        self.assertEqual(item.status, "pending")
        self.assertEqual(item.reversed_decisions.get().reviewer, approver)
        self.assertTrue(item.reversed_decisions.get().is_paid)
        self.assertIsNone(item.is_paid)
        self.client.post(decide, {"revision":"1", "choice":"rejected"})
        self.client.post(undo, {"revision":"0"})
        item.refresh_from_db()
        self.assertEqual(item.status, "rejected")
        self.client.post(undo, {"revision":"1"})
        self.client.post(decide, {"revision":"2", "choice":"approved"})
        self.assertIs(Day.objects.get(source=item).is_paid, False)

    def test_manual_paid_holiday_range(self):
        admin = User.objects.create_user("admin", is_staff=True)
        self.client.force_login(admin)
        self.client.post("/unos/", {"kind":"holiday", "holiday_name":"New Year", "scope":"all",
                                    "start":"01/01/2027", "end":"01/02/2027", "is_paid":"on"})
        self.assertEqual(Day.objects.filter(is_paid=True).count(), 2)
        self.assertContains(self.client.get("/?dan=2027-01-01"), "PTO (paid)")
