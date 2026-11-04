from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from .models import KINDS, LEAVE, JobRole, EntryType


DATE_FORMATS = ("%d.%m.%Y.", "%d.%m.%Y")


class Period(forms.Form):
    kind = forms.ChoiceField(label="Vrsta odsustva", choices=LEAVE)
    start = forms.DateField(label="Od", input_formats=DATE_FORMATS, widget=forms.TextInput(attrs={"placeholder": "DD.MM.GGGG."}))
    end = forms.DateField(label="Do", required=False, input_formats=DATE_FORMATS, help_text="Za jedan dan ostavite prazno.", widget=forms.TextInput(attrs={"placeholder": "DD.MM.GGGG."}))

    def clean(self):
        data = super().clean()
        start = data.get("start")
        end = data["end"] = data.get("end") or start
        if start and end and (end < start or (end - start).days > 365):
            raise forms.ValidationError("Izaberite period od jednog do 366 dana.")
        return data


class Ask(Period):
    note = forms.CharField(label="Napomena", required=False, max_length=2000, widget=forms.Textarea(attrs={"rows": 3}))


class People(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.get_full_name() or obj.username} ({obj.username})"


class Entry(Period):
    field_order = ["kind", "holiday_name", "start", "end", "scope", "workers"]
    holiday_name = forms.CharField(label="Naziv praznika (opciono)", max_length=100, required=False)
    kind = forms.ChoiceField(label="Vrsta unosa", choices=KINDS)
    scope = forms.ChoiceField(label="Obuhvat", choices=[("all", "Svi aktivni radnici"), ("selected", "Izabrana imena")])
    workers = People(label="Izabrana imena", queryset=User.objects.filter(is_active=True).order_by("first_name", "username"), required=False, widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = KINDS + [(f"custom-{pk}", name) for pk, name in EntryType.objects.values_list("pk", "name")]

    def clean(self):
        data = super().clean()
        if data.get("scope") == "selected" and not data.get("workers"):
            self.add_error("workers", "Izaberite barem jednu osobu.")
        return data


class RoleSelection(forms.Form):
    job_role = forms.ModelChoiceField(label="Poslovna rola", queryset=JobRole.objects.all(), empty_label="Izaberite rolu")


class Member(RoleSelection):
    name = forms.CharField(label="Ime i prezime", max_length=150)
    username = forms.RegexField(label="Korisničko ime", regex=r"^[\w.@+-]+$", max_length=150)
    password = forms.CharField(label="Lozinka", min_length=12, max_length=128, widget=forms.PasswordInput)
    role = forms.ChoiceField(label="Ovlašćenja", choices=[("worker", "Član tima"), ("admin", "Administrator")])


class Registration(RoleSelection):
    name = forms.CharField(label="Ime i prezime", max_length=150)
    email = forms.EmailField(label="E-mail", max_length=150)
    password = forms.CharField(label="Lozinka", min_length=12, max_length=128, strip=False,
                               help_text="Najmanje 12 znakova.", widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("Ova adresa se već koristi.")
        return email


class TeamLogin(AuthenticationForm):
    def clean_username(self):
        username = self.cleaned_data["username"]
        if "@" in username and username != username.lower() and not User.objects.filter(username=username).exists():
            return username.lower()
        return username
