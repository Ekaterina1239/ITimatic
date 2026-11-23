import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.http import require_POST

from .models import LoginCode, Profile, normalize_phone
from .notify import send_sms
from .roles import ROLE_LABEL, user_roles


def _h(phone, code):
    return salted_hmac("itmatic-login", f"{phone}:{code}").hexdigest()


def set_lang(request, code):
    if code in ("en", "ru", "uz"):
        request.session["lang"] = code
        if request.user.is_authenticated:
            Profile.objects.filter(user=request.user).update(lang=code)
    return redirect(request.META.get("HTTP_REFERER") or "/")


def login_phone(request):
    """Figure 1. Same answer whether or not the number exists (no account enumeration); max 3 codes / 10 min."""
    if request.method == "POST":
        ph = normalize_phone(request.POST.get("phone", ""))
        request.session["login_phone"] = ph
        request.session.pop("demo_code", None)
        recent = LoginCode.objects.filter(phone=ph, created_at__gte=timezone.now() - timedelta(minutes=10)).count()
        if ph and recent < 3 and Profile.objects.filter(phone=ph).exists():
            code = f"{secrets.randbelow(10**6):06d}"
            LoginCode.objects.create(phone=ph, code_hash=_h(ph, code))
            send_sms(ph, f"ITmatic code: {code}")
            if settings.SMS_DEMO:
                request.session["demo_code"] = code
        return redirect("login_verify")
    return render(request, "login_phone.html")


def login_verify(request):
    """Figure 2."""
    ph = request.session.get("login_phone")
    if not ph:
        return redirect("login_phone")
    error = False
    if request.method == "POST":
        lc = LoginCode.objects.filter(phone=ph, used=False, created_at__gte=timezone.now() - timedelta(minutes=5)).order_by("-created_at").first()
        ok = False
        if lc and lc.attempts < 5:
            lc.attempts += 1
            ok = hmac.compare_digest(lc.code_hash, _h(ph, request.POST.get("code", "").strip()))
            lc.used = ok
            lc.save()
        if ok:
            prof = Profile.objects.select_related("user").get(phone=ph)
            lang = request.session.get("lang") or prof.lang
            login(request, prof.user, backend="django.contrib.auth.backends.ModelBackend")
            request.session["lang"] = lang
            request.session.pop("login_phone", None); request.session.pop("demo_code", None)
            roles = user_roles(prof.user)
            if len(roles) > 1:
                return redirect("select_role")
            request.session["role"] = roles[0] if roles else None
            return redirect("/")
        error = True
    return render(request, "login_verify.html", {"error": error, "phone": ph, "demo_code": request.session.get("demo_code")})


def select_role(request):
    """Figure 3: several roles on one phone number -> choose a workspace; one role -> straight in."""
    if not request.user.is_authenticated:
        return redirect("login_phone")
    roles = user_roles(request.user)
    if request.method == "POST":
        if request.POST.get("role") in roles:
            request.session["role"] = request.POST["role"]
            return redirect("/")
    if len(roles) == 1:
        request.session["role"] = roles[0]
        return redirect("/")
    return render(request, "select_role.html", {"options": [(r, ROLE_LABEL[r]) for r in roles]})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login_phone")
