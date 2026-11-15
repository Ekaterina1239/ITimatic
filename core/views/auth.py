"""Sign-in by phone + SMS code, role selection and interface language."""

from django.conf import settings
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from ..models import LANGUAGES, ROLES, User
from .common import HOME


def login_view(request):
    error = ""
    if request.method == "POST":
        digits = "".join(c for c in request.POST.get("phone", "") if c.isdigit())[-9:]
        if User.objects.filter(phone=digits).exists():
            request.session["pp"] = digits
            return redirect("verify")
        error = _("Unregistered number. Contact the administrator.")
    return render(request, "auth.html", {"step": "phone", "err": error})


def verify(request):
    phone = request.session.get("pp")
    if not phone:
        return redirect("login")
    error = ""
    if request.method == "POST":
        if request.POST.get("code") == settings.SMS_DEMO_CODE:
            user = User.objects.get(phone=phone)
            chosen = request.session.get("lang")  # picked on the login screen
            login(request, user)
            if chosen and chosen != user.language:
                user.language = chosen
                user.save(update_fields=["language"])
            roles = user.role_codes()
            if len(roles) == 1:
                request.session["role"] = roles[0]
                return redirect("home")
            return redirect("role")
        error = _("Wrong code. Check the 6 digits and try again.")
    return render(request, "auth.html", {"step": "verify", "err": error, "phone": phone})


def choose_role(request):
    if not request.user.is_authenticated:
        return redirect("login")
    names = dict(ROLES)
    roles = [(code, names[code]) for code in request.user.role_codes()]
    if request.method == "POST" and request.POST.get("role") in dict(roles):
        request.session["role"] = request.POST["role"]
        return redirect("home")
    return render(request, "auth.html", {"step": "role", "roles": roles})


def logout_view(request):
    logout(request)
    return redirect("login")


def home(request):
    role = request.session.get("role")
    if request.user.is_authenticated and role:
        return redirect(HOME[role])
    return redirect("login")


@require_POST
def set_language(request):
    """NFR-02: the user changes the language; it is stored on the account."""
    code = request.POST.get("language")
    if code in dict(LANGUAGES):
        request.session["lang"] = code
        if request.user.is_authenticated:
            request.user.language = code
            request.user.save(update_fields=["language"])
        translation.activate(code)
    return redirect(request.POST.get("next") or "home")
