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
        self.client.post(decide, {"choice":"approved", "comment":"First decision"})
        self.assertTrue(Day.objects.filter(source=item).exists())
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
        self.client.post(decide, {"revision":"1", "choice":"rejected"})
        self.client.post(undo, {"revision":"0"})
        item.refresh_from_db()
        self.assertEqual(item.status, "rejected")
        self.client.post(undo, {"revision":"1"})
        self.client.post(decide, {"revision":"2", "choice":"approved"})
        self.assertEqual(Day.objects.filter(source=item).count(), 1)
