from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from . import views
from .forms import TeamLogin

urlpatterns = [
    path("", views.calendar_view, name="calendar"),
    path("prijava/", LoginView.as_view(template_name="login.html", authentication_form=TeamLogin), name="login"),
    path("registracija/", views.register, name="register"),
    path("tim/<int:pk>/odobri/", views.approve_member, name="approve_member"),
    path("odjava/", LogoutView.as_view(), name="logout"),
    path("trazi/", views.ask, name="ask"),
    path("unos/", views.entry, name="entry"),
    path("unos/vrsta/<int:pk>/boja/", views.type_color, name="type_color"),
    path("moji/", views.mine, name="mine"),
    path("moji/<int:pk>/procitano/", views.acknowledge, name="acknowledge"),
    path("moji/<int:pk>/povuci/", views.withdraw, name="withdraw"),
    path("zahtjevi/", views.queue, name="queue"),
    path("zahtjevi/<int:pk>/odluka/", views.decide, name="decide"),
    path("tim/", views.team, name="team"),
    path("tim/role/", views.add_role, name="add_role"),
    path("tim/<int:pk>/rola/", views.assign_role, name="assign_role"),
    path("tim/<int:pk>/administrator/", views.promote, name="promote"),
    path("tim/<int:pk>/arhiviraj/", views.archive, name="archive"),
]
