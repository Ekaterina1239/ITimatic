from django import template
from django.utils.safestring import mark_safe
from ..notify import render_text
from ..translations import TR

register = template.Library()


@register.simple_tag(takes_context=True)
def t(context, text):
    """NFR-02: EN / RU / UZ interface. Falls back to the English text."""
    return TR.get(context.get("lang", "en"), {}).get(str(text), str(text))


@register.simple_tag(takes_context=True)
def note(context, n):
    return render_text(n.template, n.params, context.get("lang", "en"))


@register.filter
def som(n):
    try:
        return f"{int(n):,}".replace(",", " ") + " so'm"
    except (TypeError, ValueError):
        return "-"


@register.filter
def split_pairs(s):
    return [p.split(":") for p in s.split(",")]


@register.filter
def get(d, k):
    return d.get(k)


ICONS = {
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "userplus": '<circle cx="9" cy="8" r="4"/><path d="M2 21c0-4 3-6 7-6s7 2 7 6M19 8v6M16 11h6"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2 20c0-4 3-6 7-6s7 2 7 6"/><path d="M17 4.5a3.5 3.5 0 010 7M22 20c0-3-2-5-5-5.7"/>',
    "wallet": '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 10h18M16 15h2"/>',
    "card": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
    "chart": '<path d="M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-3"/>',
    "bell": '<path d="M6 16V11a6 6 0 0112 0v5l2 2H4zM10 21h4"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "award": '<circle cx="12" cy="9" r="6"/><path d="M8.5 14L7 22l5-3 5 3-1.5-8"/>',
    "home": '<path d="M3 11l9-8 9 8v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z"/>',
    "send": '<path d="M22 2L11 13M22 2l-7 20-4-9-9-4z"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "alert": '<path d="M12 3l10 18H2zM12 10v5M12 18h.01"/>',
    "file": '<path d="M6 3h8l5 5v13H6zM14 3v5h5"/>',
    "logout": '<path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/>',
    "book": '<path d="M4 4h7a3 3 0 013 3v14a2 2 0 00-2-2H4zM20 4h-6M20 4v15h-6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
}


@register.simple_tag
def icon(name, size=18):
    return mark_safe(f'<svg class="ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS.get(name, "")}</svg>')
