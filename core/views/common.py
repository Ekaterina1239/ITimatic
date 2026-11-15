"""Shared helpers: role-based access (NFR-01) and navigation."""

from functools import wraps

from django.shortcuts import redirect

HOME = {
    "admin": "overview",
    "director": "overview",
    "edmgr": "overview",
    "accountant": "finance",
    "teacher": "teacher",
    "parent": "children",
    "student": "dash",
}
STAFF = ("admin", "director", "edmgr")

# (url name, label, icon). Items in LOCKED_FOR are shown greyed out with a lock
# so the role can see that the area exists but is not part of its access (NFR-01).
NAV = {
    "admin": [("overview", "Overview", "grid"), ("enrolment", "Enrolment", "userplus"), ("schedule", "Schedule", "calendar"),
              ("groups", "Groups", "users"), ("finance", "Finance", "wallet"), ("debtors", "Debtors", "card"),
              ("reports", "Reports", "chart")],
    "director": [("overview", "Overview", "grid"), ("schedule", "Schedule", "calendar"), ("groups", "Groups", "users"),
                 ("finance", "Finance", "wallet"), ("debtors", "Debtors", "card"), ("reports", "Reports", "chart")],
    "edmgr": [("overview", "Overview", "grid"), ("schedule", "Schedule", "calendar"), ("groups", "Groups", "users"),
              ("reports", "Reports", "chart")],
    "accountant": [("overview", "Overview", "grid", True), ("enrolment", "Enrolment", "userplus", True),
                   ("schedule", "Schedule", "calendar", True), ("groups", "Groups", "users", True),
                   ("finance", "Finance", "wallet"), ("debtors", "Debtors", "card"), ("pay", "Take payment", "card"),
                   ("reports", "Reports", "chart")],
    "teacher": [("teacher", "My workspace", "grid"), ("schedule", "My timetable", "calendar"),
                ("leave", "Leave requests", "coffee"), ("reports", "Results & certificates", "chart")],
    "parent": [("dash", "My children", "home"), ("fschedule", "Lessons", "calendar"), ("absence", "Report absence", "send"),
               ("attendance", "Attendance", "check"), ("grades", "Results", "chart"), ("materials", "Materials", "book2"),
               ("payments", "Payments", "wallet")],
    "student": [("dash", "My learning", "home"), ("fschedule", "Timetable", "calendar"), ("grades", "Results", "chart"),
                ("materials", "Materials", "book2"), ("attendance", "Attendance", "check"), ("absence", "Report absence", "send"),
                ("payments", "Payments", "wallet")],
}
NAV_LABELS = {item[0]: item[1] for items in NAV.values() for item in items}
NAV_LABELS.update({"applicant": "Enrolment", "pay": "Take payment", "substitute": "Schedule", "children": "My children",
                   "tatt": "Lesson form", "receipt": "Receipt", "open_student": "Debtors"})


def role_required(*roles):
    """Allow the view only for a signed-in user acting in one of `roles`."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")
            if request.session.get("role") not in roles:
                return redirect("home")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def nav(request):
    """Template context processor: menu items for the current role."""
    from ..models import LANGUAGES

    role = request.session.get("role")
    from ..models import ROLES

    items = [
        {"name": it[0], "label": it[1], "icon": it[2], "locked": len(it) > 3}
        for it in NAV.get(role, [])
    ]
    match = getattr(request, "resolver_match", None)
    current = match.url_name if match else ""
    staff = role in ("admin", "director", "edmgr", "accountant")
    return {
        "nav": items,
        "role": role,
        "role_label": dict(ROLES).get(role, ""),
        "languages": LANGUAGES,
        "crumb": next((i["label"] for i in items if i["name"] == current), NAV_LABELS.get(current, "")),
        "workspace": ("Center workspace", "Chilonzor / Yunusobod") if staff else ("Personal workspace", "Autumn term · 2026"),
        "crumb_root": "Workspace" if staff else "ITmatic learning",
    }
