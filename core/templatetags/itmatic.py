from django import template

register = template.Library()


@register.filter
def som(value):
    """480000 -> '480 000 so‘m' (NFR-02: currency is never translated)."""
    try:
        return f"{int(value):,}".replace(",", " ") + " so‘m"
    except (TypeError, ValueError):
        return value


@register.filter
def label(value):
    """'not_marked' -> 'Not marked' (used as a msgid for translation)."""
    return str(value).replace("_", " ").capitalize()


@register.filter
def tl(value):
    """Translate a value stored in the database: 'not_marked' -> 'Не отмечен'."""
    from django.utils.translation import gettext

    return gettext(label(value))


# Simple line icons (24×24, stroke = currentColor) used by the sidebar and buttons.
ICONS = {
    "grid": "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
    "userplus": "M15 20a6 6 0 0 0-12 0M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM19 8v6M16 11h6",
    "calendar": "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
    "users": "M16 20a5 5 0 0 0-10 0M11 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM21 20a4.5 4.5 0 0 0-4-4.4M16 4.3a3.5 3.5 0 0 1 0 6.4",
    "wallet": "M4 7h15a1 1 0 0 1 1 1v11H4zM4 7V5h12v2M16 13h2",
    "chart": "M4 4v16h16M8 15l4-4 3 3 5-6",
    "message": "M4 5h16v11H9l-5 4z",
    "settings": "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1",
    "bell": "M6 16v-5a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0",
    "search": "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
    "book": "M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5zM5 4.5v15A1.5 1.5 0 0 0 6.5 21H19v-3M9 7h6",
    "plus": "M12 5v14M5 12h14",
    "arrow": "M5 12h14M13 6l6 6-6 6",
    "back": "M19 12H5M11 6l-6 6 6 6",
    "alert": "M12 3 22 21H2zM12 10v4M12 17.5v.01",
    "info": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7.5v.01",
    "check": "M5 12l5 5 9-10",
    "download": "M12 4v11M7 10l5 5 5-5M5 20h14",
    "send": "M4 12 20 4l-6 16-3-7z",
    "lock": "M6 11h12v9H6zM8 11V8a4 4 0 0 1 8 0v3",
    "clock": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
    "file": "M6 3h9l4 4v14H6zM14 3v5h5",
    "logout": "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10",
    "updown": "M8 9l4-4 4 4M8 15l4 4 4-4",
    "chev": "M6 9l6 6 6-6",
    "shield": "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
    "doc": "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
    "coffee": "M5 9h11v5a5 5 0 0 1-10 0zM16 10h2a2 2 0 0 1 0 4h-2M8 3v3M12 3v3",
    "home": "M4 11 12 4l8 7v9H4z",
    "book2": "M4 5h6a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H4zM20 5h-6a2 2 0 0 0-2 2v13a2 2 0 0 1 2-2h6z",
    "card": "M3 6h18v12H3zM3 10h18",
}


@register.simple_tag
def icon(name, size=16):
    from django.utils.safestring import mark_safe

    d = ICONS.get(name, ICONS["info"])
    return mark_safe(
        f'<svg class="ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{d}"/></svg>'
    )


@register.filter
def initials(value):
    parts = str(value).split()
    return "".join(p[0] for p in parts[:2]).upper()


@register.filter
def pill(status):
    """CSS tone for a status word."""
    s = str(status).lower()
    if s in ("paid", "present", "completed", "confirmed", "approved", "active", "received", "signed", "attended",
             "accepted", "interested", "wants to join", "graded", "eligible", "reported", "trial completed", "submitted"):
        return "ok"
    if s in ("overdue", "unexplained", "absent", "rejected", "lost", "cancelled", "conflict", "declines", "unpaid",
             "not suitable", "did not attend"):
        return "bad"
    if s in ("due", "late", "excused", "pending", "waiting list", "trial booked", "partially paid", "draft",
             "cover pending", "scheduled", "upcoming", "attendance due", "undecided", "wants another group", "group matching", "prepared", "assessment", "enquiry"):
        return "warn"
    if s in ("agreement", "in progress", "substitute", "substitute teacher", "make-up", "selected"):
        return "pri"
    return "mute"


@register.filter
def pct_of(value, total):
    try:
        return max(0, min(100, round(100 * float(value) / float(total))))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


@register.simple_tag
def linechart(values, width=440, height=150, labels="", ymin=None, ymax=None, suffix=""):
    """Small SVG line chart with grid lines, as in the Figma charts."""
    from django.utils.safestring import mark_safe

    vals = [float(v) for v in values] or [0]
    lo = min(vals) if ymin is None else float(ymin)
    hi = max(vals) if ymax is None else float(ymax)
    if hi == lo:
        hi = lo + 1
    pad_l, pad_b, pad_t = 34, 22, 8
    w, h = width - pad_l - 18, height - pad_b - pad_t
    pts = []
    for i, v in enumerate(vals):
        x = pad_l + (w * i / max(len(vals) - 1, 1))
        y = pad_t + h - (v - lo) / (hi - lo) * h
        pts.append(f"{x:.1f},{y:.1f}")
    grid = ""
    for k in range(3):
        y = pad_t + h * k / 2
        val = hi - (hi - lo) * k / 2
        grid += (f'<line x1="{pad_l}" x2="{width - 6}" y1="{y:.1f}" y2="{y:.1f}" stroke="#ecebe7"/>'
                 f'<text x="{pad_l - 6}" y="{y + 3:.1f}" text-anchor="end" font-size="10" fill="#a1a2aa">{val:.0f}{suffix}</text>')
    labs = labels.split(",") if labels else []
    lab_svg = ""
    for i, t in enumerate(labs):
        x = pad_l + (w * i / max(len(labs) - 1, 1))
        lab_svg += f'<text x="{x:.1f}" y="{height - 4}" text-anchor="middle" font-size="10" fill="#a1a2aa">{t}</text>'
    return mark_safe(
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" preserveAspectRatio="none" class="chart">{grid}'
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="#5353ad" stroke-width="2" stroke-linejoin="round"/>{lab_svg}</svg>'
    )


@register.simple_tag
def spark(values):
    from django.utils.safestring import mark_safe

    vals = [float(v) for v in values] or [1]
    hi = max(vals) or 1
    bars = "".join(
        f'<rect x="{i * 7}" y="{28 - 26 * v / hi:.1f}" width="4" height="{26 * v / hi:.1f}" rx="1" '
        f'fill="{"#5353ad" if i == len(vals) - 1 else "#d9d8f0"}"/>'
        for i, v in enumerate(vals)
    )
    return mark_safe(f'<svg width="{len(vals) * 7}" height="28" class="spark">{bars}</svg>')
