from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from .models import KINDS, LEAVE, JobRole, EntryType


DATE_FORMATS = ("%d.%m.%Y.", "%d.%m.%Y")


class Period(forms.Form):
    kind = forms.ChoiceField(label="Leave type", choices=LEAVE)
    start = forms.DateField(label="From", input_formats=DATE_FORMATS, widget=forms.TextInput(attrs={"placeholder": "DD.MM.YYYY."}))
    end = forms.DateField(label="To", required=False, input_formats=DATE_FORMATS, help_text="Leave blank for a single day.", widget=forms.TextInput(attrs={"placeholder": "DD.MM.YYYY."}))

    def clean(self):
        data = super().clean()
        start = data.get("start")
        end = data["end"] = data.get("end") or start
        if start and end and (end < start or (end - start).days > 365):
            raise forms.ValidationError("Choose a period between 1 and 366 days.")
        return data


class Ask(Period):
    note = forms.CharField(label="Note", required=False, max_length=2000, widget=forms.Textarea(attrs={"rows": 3}))


class People(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.get_full_name() or obj.username} ({obj.username})"


class Entry(Period):
    field_order = ["kind", "holiday_name", "start", "end", "scope", "workers"]
    holiday_name = forms.CharField(label="Holiday name (optional)", max_length=100, required=False)
    kind = forms.ChoiceField(label="Entry type", choices=KINDS)
    scope = forms.ChoiceField(label="Applies to", choices=[("all", "All active team members"), ("selected", "Selected members")])
    workers = People(label="Selected members", queryset=User.objects.filter(is_active=True).order_by("first_name", "username"), required=False, widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = KINDS + [(f"custom-{pk}", name) for pk, name in EntryType.objects.values_list("pk", "name")]

    def clean(self):
        data = super().clean()
        if data.get("scope") == "selected" and not data.get("workers"):
            self.add_error("workers", "Select at least one team member.")
        return data


class RoleSelection(forms.Form):
    job_role = forms.ModelChoiceField(label="Job role", queryset=JobRole.objects.all(), empty_label="Select a role")


class Member(RoleSelection):
    name = forms.CharField(label="Full name", max_length=150)
    username = forms.RegexField(label="Username", regex=r"^[\w.@+-]+$", max_length=150)
    password = forms.CharField(label="Password", min_length=12, max_length=128, widget=forms.PasswordInput)
    role = forms.ChoiceField(label="Access level", choices=[("worker", "Team member"), ("admin", "Administrator")])


class Registration(RoleSelection):
    name = forms.CharField(label="Full name", max_length=150)
    email = forms.EmailField(label="Email", max_length=150)
    password = forms.CharField(label="Password", min_length=12, max_length=128, strip=False,
                               help_text="Use at least 12 characters.", widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("This email address is already in use.")
        return email


class TeamLogin(AuthenticationForm):
    def clean_username(self):
        username = self.cleaned_data["username"]
        if "@" in username and username != username.lower() and not User.objects.filter(username=username).exists():
            return username.lower()
        return username
