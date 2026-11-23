from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

ROLES = ("accountant", "admin", "teacher", "parent", "student")
VIEW_PEOPLE = ("admin",)
ROLE_LABEL = {"admin": "Administrator", "teacher": "Teacher", "parent": "Parent", "student": "Student",
              "accountant": "Accountant"}


def user_roles(user):
    """NFR-01: one phone number may carry several roles (design: 'Select role' screen)."""
    if not user.is_authenticated:
        return []
    names = set(user.groups.values_list("name", flat=True))
    if user.is_superuser:
        names.add("admin")
    return [r for r in ROLES if r in names]


def role(user):
    """The ACTIVE role of the current request (set by RoleMiddleware from the session)."""
    return getattr(user, "_active_role", None)


class RoleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        u = request.user
        if u.is_authenticated:
            roles = user_roles(u)
            chosen = request.session.get("role")
            u._active_role = chosen if chosen in roles else (roles[0] if len(roles) == 1 else None)
            u._roles = roles
        return self.get_response(request)


def role_required(*roles):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapper(request, *a, **kw):
            r = role(request.user)
            if r is None and len(getattr(request.user, "_roles", [])) > 1:
                return redirect("select_role")
            if r not in roles:
                raise PermissionDenied
            return view(request, *a, **kw)
        return wrapper
    return deco
