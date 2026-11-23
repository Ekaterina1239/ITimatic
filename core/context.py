from .roles import role, ROLE_LABEL


def ctx(request):
    u = getattr(request, "user", None)
    out = {"lang": request.session.get("lang", "en") if hasattr(request, "session") else "en", "LANGS": ["en", "ru", "uz"], "role": None}
    if u is not None and u.is_authenticated:
        r = role(u)
        out.update(role=r, role_label=ROLE_LABEL.get(r, ""), roles=getattr(u, "_roles", []),
                   unread=u.notifications.filter(read=False).count())
    return out
