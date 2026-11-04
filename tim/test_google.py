from time import time
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from .models import JobRole


@override_settings(GOOGLE_CLIENT_ID="test-client")
class GoogleSignInTests(TestCase):
    @override_settings(GOOGLE_REDIRECT_ENABLED=True)
    @patch("tim.google_login.verify_oauth2_token")
    def test_google_redirect_verifies_csrf_and_opens_profile(self, verify):
        self.assertContains(self.client.get("/registracija/"), 'data-ux_mode="redirect"')
        self.client.cookies["g_csrf_token"] = "browser-token"
        url = "/auth/google/return/"
        self.assertRedirects(self.client.post(url, {"g_csrf_token":"wrong"}), "/prijava/")
        verify.assert_not_called()
        verify.return_value = {"sub":"google-sub", "email":"member@example.com", "email_verified":True,
                               "given_name":"Ana", "exp":time()+600}
        page = self.client.post(url, {"credential":"test", "g_csrf_token":"browser-token"}, follow=True)
        self.assertContains(page, "Complete your registration")
        self.assertContains(page, 'value="Ana"')

    @patch("tim.google_login.verify_oauth2_token")
    def test_manual_names_and_approval(self, verify):
        verify.return_value = {"sub": "google-sub", "email": "member@example.com", "email_verified": True,
                               "given_name": "Anita", "family_name": "Smith", "exp": time() + 1000}
        endpoint = "/auth/google/verify/"
        self.assertContains(self.client.get("/registracija/"), "g_id_signin")
        self.assertRedirects(self.client.post(endpoint, {"credential": "test"}), "/auth/google/register/")
        panel = self.client.get("/auth/google/register/")
        self.assertContains(panel, 'value="Anita"')
        self.assertContains(panel, 'value="Smith"')
        data = {"job_role": JobRole.objects.first().pk, "first_name": "Ana"}
        self.client.post("/auth/google/register/", data)
        self.assertFalse(User.objects.exists())
        self.client.post("/auth/google/register/", {**data, "last_name": "Kovac", "is_staff": True})
        member = User.objects.get()
        self.assertEqual(member.get_full_name(), "Ana Kovac")
        self.assertFalse(member.is_active or member.is_staff or member.has_usable_password())
        self.client.post(endpoint, {"credential": "test"})
        self.assertNotIn("_auth_user_id", self.client.session)
        member.is_active = True
        member.save()
        self.assertRedirects(self.client.post(endpoint, {"credential": "test"}), "/")

    @patch("tim.google_login.verify_oauth2_token")
    def test_invalid_token_and_email_collision(self, verify):
        User.objects.create_user("existing", email="owner@example.com")
        verify.side_effect = ValueError("invalid")
        self.client.post("/auth/google/verify/", {"credential": "invalid"})
        self.assertNotIn("google_signup", self.client.session)
        verify.side_effect = None
        verify.return_value = {"sub": "new", "email": "owner@example.com", "email_verified": True, "exp": time()+1000}
        self.client.post("/auth/google/verify/", {"credential": "test"})
        self.assertNotIn("google_signup", self.client.session)
        self.assertNotIn("_auth_user_id", self.client.session)
