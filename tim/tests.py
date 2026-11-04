from datetime import date
from django.contrib.auth.models import User
from django.test import Client, TestCase
from .models import Day, LeaveRequest, JobRole, MemberRole, EntryType


class TeamFlow(TestCase):
    def setUp(self):
        self.clients = {}
        for username in ["Ana", "Marko", "Iva", "Ema"]:
            User.objects.create_user(username, password="tajna-za-test", is_staff=username in ["Iva","Ema"])
            client = Client()
            response = client.post("/prijava/", {"username": username, "password":"tajna-za-test"})
            self.assertRedirects(response, "/")
            self.clients[username] = client
        self.ana, self.marko, self.admin, self.other = self.clients.values()
        self.friday = date(2026,11,6)
        self.url = "/?dan=2026-11-06"

    def test_calendar_role_filter(self):
        editor = JobRole.objects.get(name="Video Editor")
        ana = User.objects.get(username="Ana")
        marko = User.objects.get(username="Marko")
        MemberRole.objects.create(user=ana, role=editor)
        MemberRole.objects.create(user=marko, role=JobRole.objects.get(name="Media Buyer"))
        Day.objects.create(worker=ana, date=self.friday, kind="free")
        Day.objects.create(worker=marko, date=self.friday, kind="vacation")
        url = self.url + f"&rola={editor.pk}"
        page = self.marko.get(url)
        self.assertEqual([row.worker_id for row in page.context["rows"]], [ana.pk])
        cell = next(c for c in page.context["cells"] if c["date"] == self.friday)
        self.assertEqual(cell["kinds"], [("free", "Slobodan dan")])
        self.assertContains(page, f'&amp;rola={editor.pk}"')
        self.assertFalse(self.marko.get(url + f"&osoba={marko.pk}").context["rows"])

    def test_custom_entry_type(self):
        payload = {"action": "add_type", "name": "Edukacija", "color": "teal"}
        self.assertEqual(self.ana.post("/unos/", payload).status_code, 403)
        page = self.admin.post("/unos/?datum=06.11.2026.", payload, follow=True)
        kind = f"custom-{EntryType.objects.get(name='Edukacija').pk}"
        self.assertEqual(page.context["form"]["kind"].value(), kind)
        self.assertEqual(page.context["form"]["start"].value(), "06.11.2026.")
        self.other.post("/unos/", {"kind":kind, "start":"06.11.2026.", "scope":"all"})
        self.assertEqual({row.label for row in self.ana.get(self.url).context["rows"]}, {"Edukacija"})
        self.assertContains(self.ana.get(self.url), 'class="tag custom role-teal">Edukacija</span>', count=6)
        color_url = f"/unos/vrsta/{EntryType.objects.get(name='Edukacija').pk}/boja/"
        self.assertEqual(self.ana.post(color_url, {"color":"blue"}).status_code, 403)
        self.assertEqual(self.admin.post(color_url, {"color":"unknown"}).status_code, 400)
        self.assertEqual(self.admin.post(color_url, {"color":"blue"}).status_code, 302)
        self.assertContains(self.ana.get(self.url), 'class="tag custom role-blue">Edukacija</span>', count=6)
        self.admin.post("/unos/", {"action":"add_type", "name":"edukacija"})
        self.assertEqual(EntryType.objects.count(), 1)

    def ask(self):
        self.ana.post("/trazi/", {"kind":"free","start":"06.11.2026.","note":"Privatna napomena"})
        return LeaveRequest.objects.latest("id")

    def test_friday(self):
        self.admin.post("/unos/", {"kind":"vacation","start":"06.11.2026.","scope":"selected","workers":[User.objects.get(username="Marko").pk]})
        item = self.ask()
        decision = f"/zahtjevi/{item.pk}/odluka/"
        self.assertContains(self.ana.get("/moji/"), "Na čekanju")
        self.assertNotContains(self.marko.get("/moji/"), "Privatna napomena")
        self.assertEqual(self.marko.get("/zahtjevi/").status_code, 403)
        self.assertNotContains(self.marko.get(self.url), "Privatna napomena")
        self.assertEqual(self.ana.post(decision, {"choice":"approved"}).status_code, 403)
        for client in (self.admin, self.other):
            page = client.get("/zahtjevi/")
            self.assertContains(page, "Privatna napomena")
            self.assertContains(page, "Marko · 06.11.2026. · Godišnji odmor")
        self.admin.post(decision, {"choice":"approved","comment":"Dogovoreno"})
        second = self.other.post(decision, {"choice":"rejected"}, follow=True)
        self.assertContains(second, "već obrađen")
        item.refresh_from_db()
        self.assertEqual(item.reviewer.username, "Iva")
        self.assertIsNotNone(item.decided)
        self.marko.post(f"/moji/{item.pk}/procitano/")
        self.assertContains(self.ana.get("/"), "Vaš zahtjev je odobren.")
        self.assertNotContains(self.marko.get("/"), "Dogovoreno")
        self.ana.post(f"/moji/{item.pk}/procitano/")
        self.assertNotContains(self.ana.get("/"), "Vaš zahtjev je odobren.")
        self.assertContains(self.ana.get("/moji/"), "Odobreno")
        self.assertContains(self.ana.get("/moji/"), "Dogovoreno")
        for client in self.clients.values():
            rows = client.get(self.url).context["rows"]
            self.assertEqual({(r.worker.username,r.kind) for r in rows}, {("Ana","free"),("Marko","vacation")})
        duplicate = self.ask()
        self.admin.post(f"/zahtjevi/{duplicate.pk}/odluka/", {"choice":"approved"})
        duplicate.refresh_from_db()
        self.assertEqual(duplicate.status, "pending")
        self.assertEqual(Day.objects.count(), 2)

    def test_reject_withdraw(self):
        item = self.ask()
        self.admin.post(f"/zahtjevi/{item.pk}/odluka/", {"choice":"rejected","comment":"Drugi termin"})
        page = self.ana.get("/moji/")
        self.assertContains(page, "Odbijeno")
        self.assertContains(page, "Drugi termin")
        item = self.ask()
        url = f"/moji/{item.pk}/povuci/"
        self.marko.post(url)
        item.refresh_from_db()
        self.assertEqual(item.status,"pending")
        self.ana.post(url)
        self.admin.post(f"/zahtjevi/{item.pk}/odluka/", {"choice":"approved"})
        item.refresh_from_db()
        self.assertEqual(item.status, "withdrawn")
        self.assertFalse(Day.objects.exists())

    def test_promote_member(self):
        ana = User.objects.get(username="Ana")
        url = f"/tim/{ana.pk}/administrator/"
        self.assertEqual(self.ana.post(url).status_code, 403)
        self.assertEqual(self.admin.get(url).status_code, 405)
        self.assertRedirects(self.admin.post(url), "/tim/")
        self.assertEqual(self.ana.get("/zahtjevi/").status_code, 200)
        self.assertEqual(self.admin.get("/zahtjevi/").status_code, 200)

    def test_registration_approval(self):
        guest = Client()
        credentials = {"username": "Lana@example.org", "password": "Moja-lozinka-123"}
        guest.post("/registracija/", {"name": "Lana", "email": credentials["username"], "password": credentials["password"]})
        self.assertFalse(User.objects.filter(email__iexact=credentials["username"]).exists())
        response = guest.post("/registracija/", {"name": "Lana", "email": credentials["username"],
                              "job_role": JobRole.objects.get(name="Video Editor").pk,
                              "password": credentials["password"], "is_staff": "1"}, follow=True)
        self.assertContains(response, "Registracija je poslana")
        member = User.objects.get(username="lana@example.org")
        self.assertEqual(member.job.role.name, "Video Editor")
        self.assertFalse(member.is_staff)
        self.assertFalse(member.is_active)
        guest.post("/prijava/", credentials)
        self.assertEqual(guest.get("/").status_code, 302)
        self.assertNotContains(self.ana.get("/"), "Lana")
        url = f"/tim/{member.pk}/odobri/"
        self.assertEqual(self.ana.post(url).status_code, 403)
        self.assertContains(self.admin.get("/tim/"), "Odobri pristup")
        self.admin.post(url)
        self.assertRedirects(guest.post("/prijava/", credentials), "/")
        self.assertEqual(guest.get("/tim/").status_code, 403)
        self.admin.post(f"/tim/{member.pk}/arhiviraj/")
        self.other.post(url)
        member.refresh_from_db()
        self.assertFalse(member.is_active)

    def test_team_scope_and_archive(self):
        self.assertEqual(Client().get("/").status_code,302)
        self.assertEqual(self.ana.post("/unos/").status_code,403)
        self.assertEqual(self.ana.post("/tim/").status_code,403)
        self.admin.post("/tim/", {"name":"Lana", "username":"lana","password":"Duga-lozinka-123","role":"admin",
                                  "job_role": JobRole.objects.get(name="Media Buyer").pk})
        lana = User.objects.get(username="lana")
        self.assertTrue(lana.is_staff)
        self.admin.post(f"/tim/{lana.pk}/arhiviraj/")
        self.admin.post("/unos/", {"kind":"holiday","start":"05.11.2026.","end":"06.11.2026.","scope":"all"})
        self.assertEqual(Day.objects.count(),8)
        self.assertFalse(Day.objects.filter(worker=lana).exists())
        self.assertFalse(Client().login(username="lana",password="Duga-lozinka-123"))
        page = self.marko.get(self.url+"&osoba="+str(User.objects.get(username="Ana").pk))
        self.assertEqual([r.worker.username for r in page.context["rows"]],["Ana"])
        self.admin.post("/unos/", {"kind":"closed","start":"04.11.2026.","end":"06.11.2026.","scope":"all"})
        self.assertEqual(Day.objects.count(),8)
