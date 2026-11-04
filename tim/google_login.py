from functools import partial
from time import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_oauth2_token

from .forms import GoogleRegistration
from .models import GoogleIdentity, MemberRole, PendingRegistration


@require_POST
def verify(request):
    return complete_sign_in(request)


@csrf_exempt
@require_POST
def google_return(request):
    # Google's cross-site form POST uses its own double-submit CSRF token.
    cookie = request.COOKIES.get("g_csrf_token", "")
    if not cookie or not constant_time_compare(cookie, request.POST.get("g_csrf_token", "")):
        messages.error(request, "Your Google sign-in session expired. Please start again.")
        return redirect("login")
    return complete_sign_in(request)


def complete_sign_in(request):
    if not settings.GOOGLE_CLIENT_ID:
        raise Http404
    if request.user.is_authenticated:
        return redirect("calendar")
    request.session.pop("google_signup", None)
    try:
        claims = verify_oauth2_token(request.POST.get("credential", ""), partial(Request(), timeout=8), settings.GOOGLE_CLIENT_ID)
    except (ValueError, GoogleAuthError):
        messages.error(request, "Google sign-in could not be verified. Please try again.")
        return redirect("login")
    email = claims.get("email", "").strip().lower()
    subject = claims.get("sub")
    if not subject or not email or len(email) > 150 or claims.get("email_verified") is not True:
        messages.error(request, "A verified Google email address is required.")
        return redirect("login")
    identity = GoogleIdentity.objects.select_related("user").filter(subject=subject).first()
    if identity:
        if identity.user.is_active:
            login(request, identity.user)
            return redirect("calendar")
        messages.info(request, "Your account needs administrator approval before you can sign in.")
        return redirect("login")
    if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
        messages.info(request, "An account already uses this email. Sign in with your existing password.")
        return redirect("login")
    request.session.cycle_key()
    request.session["google_signup"] = {
        "email": email, "subject": subject, "expires": min(claims["exp"], time() + 600),
        "names": {"first_name": claims.get("given_name") or "", "last_name": claims.get("family_name") or ""},
    }
    return redirect("google_register")


def register(request):
    if not settings.GOOGLE_CLIENT_ID:
        raise Http404
    if request.user.is_authenticated:
        return redirect("calendar")
    signup = request.session.get("google_signup")
    if not signup or signup["expires"] <= time():
        messages.info(request, "Continue with Google to start registration.")
        return redirect("register")
    form = GoogleRegistration(request.POST if request.method == "POST" else None, initial=signup.get("names", {}))
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                user = User.objects.create_user(username=signup["email"], email=signup["email"],
                                                first_name=data["first_name"], last_name=data["last_name"], is_active=False)
                GoogleIdentity.objects.create(user=user, subject=signup["subject"])
                MemberRole.objects.create(user=user, role=data["job_role"])
                PendingRegistration.objects.create(user=user)
        except IntegrityError:
            messages.info(request, "This account already exists. Return to sign in.")
        else:
            messages.success(request, "Registration submitted. Once approved, sign in with Google.")
        request.session.pop("google_signup", None)
        return redirect("login")
    return render(request, "form.html", {"title": "Complete your registration", "form": form,
                                          "signup_email": signup["email"],
                                          "button": "Request access"})
