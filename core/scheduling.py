from datetime import timedelta
from django.db.models import Q
from .models import Lesson


def _overlap(qs, start, end, exclude):
    qs = qs.filter(status="scheduled", start__lt=end, start__gt=start - timedelta(days=1))
    if exclude:
        qs = qs.exclude(pk=exclude)
    return [l for l in qs.select_related("group") if l.start < end and l.end > start]


def room_clash(room, start, end, exclude=None):
    return _overlap(Lesson.objects.filter(room=room), start, end, exclude) if room else []


def teacher_clash(user, start, end, exclude=None):
    qs = Lesson.objects.filter(Q(substitute=user) | Q(substitute__isnull=True, group__teacher=user))
    return _overlap(qs, start, end, exclude)


def week_conflicts(lessons):
    """Lesson ids that share a room or a teacher with an overlapping lesson (design: 'Room conflict' tag)."""
    bad = {}
    ls = [l for l in lessons if l.status == "scheduled"]
    for i, a in enumerate(ls):
        for b in ls[i + 1:]:
            if a.start < b.end and b.start < a.end:
                if a.room_id and a.room_id == b.room_id:
                    bad[a.id] = bad[b.id] = "room"
                elif a.teacher and a.teacher == b.teacher:
                    bad.setdefault(a.id, "teacher"); bad.setdefault(b.id, "teacher")
    return bad
