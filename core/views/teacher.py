"""Teacher screens: today's lessons, the single lesson record (FR-02) with
offline attendance entry (NFR-03), and absence / sick-leave requests."""

import datetime as dt
import json

from django.contrib import messages
from django.db import transaction
from django.db.models import Max, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from ..models import AbsenceReport, LeaveRequest, Lesson
from .common import role_required

LESSON_STATUSES = ["present", "late", "absent"]


def with_reasons(lesson, marks):
    """An absence the parent reported before the lesson counts as excused,
    any other absence as unexplained (FR-03)."""
    reported = set(AbsenceReport.objects.filter(lesson=lesson, withdrawn=False).values_list("student_id", flat=True))
    return {sid: ("excused" if sid in reported else "unexplained") if st == "absent" else st for sid, st in marks.items()}


@role_required("teacher")
def teacher(request):
    today = timezone.localdate()
    mine = Lesson.objects.filter(
        Q(group__teacher=request.user, substitute__isnull=True) | Q(substitute=request.user)
    ).select_related("group")
    from .academic import teaching_day
    day = dt.date.fromisoformat(request.GET["d"]) if request.GET.get("d") else teaching_day(mine)
    lessons = mine.filter(date=day)
    monday = today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=1 if today.weekday() >= 5 else 0)
    leaves = list(request.user.leaves.all())

    def on_leave(d):
        return next((q for q in leaves if q.start <= d <= q.end and q.status != "Rejected"), None)

    upcoming = [l for l in mine.filter(date__gte=today, cancelled=False).order_by("date", "start") if not l.has_started()]
    next_lesson = upcoming[0] if upcoming else None
    week = []
    for i in range(5):
        d = monday + dt.timedelta(days=i)
        first = mine.filter(date=d).order_by("start").first()
        if on_leave(d):
            tag = "Sick leave"
        elif first and next_lesson and first.pk == next_lesson.pk:
            tag = "Next lesson"
        elif d == today:
            tag = "Today"
        elif first and first.completed:
            tag = "Completed"
        else:
            tag = "Scheduled" if first else ""
        week.append((d, first, tag))
    # most recent lesson whose attendance is not submitted yet
    pending = [l for l in mine.filter(date__lte=today, completed=False, cancelled=False).order_by("-date", "-start") if l.has_started()]
    to_finish = pending[0] if pending else next((l for l in mine.order_by("-date", "-start") if l.has_started()), None)
    finish_rows, counts = [], {}
    if to_finish:
        marks = {a.student_id: a.status for a in to_finish.att.all()}
        for st in to_finish.group.students.all():
            status = marks.get(st.id, "not_marked")
            counts[status] = counts.get(status, 0) + 1
            if status in ("unexplained", "not_marked"):
                finish_rows.append((st, status))
    from ..models import Assessment
    results = Assessment.objects.filter(student__group__teacher=request.user, score__isnull=False).select_related("student__group").order_by("-date")[:5]
    hour = timezone.localtime().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    return render(
        request,
        "tch.html",
        {
            "page": "today", "ls": lessons, "d": day, "p": day - dt.timedelta(days=1), "n": day + dt.timedelta(days=1),
            "today": today, "week": week, "next_lesson": next_lesson, "to_finish": to_finish, "finish_rows": finish_rows[:3],
            "finish_counts": counts, "results": results, "greeting": greeting,
            "leave": next((q for q in leaves if q.end >= today and q.status != "Rejected"), None),
            "groups": request.user.teaching.filter(active=True),
        },
    )


def _apply_lesson_record(lesson, data, files=None):
    lesson.topic = data.get("topic", "")
    lesson.homework = data.get("homework", "")
    lesson.homework_due = data.get("due") or None
    if files and files.get("file"):
        lesson.material = files["file"]
    if data.get("submit"):
        lesson.completed, lesson.draft = True, False
    else:
        lesson.draft = True
    lesson.save()


@role_required("teacher")
def tatt(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    if not lesson.taught_by(request.user):
        return redirect("teacher")
    students = lesson.group.students.all()
    reported = {r.student_id: r for r in AbsenceReport.objects.filter(lesson=lesson, withdrawn=False)}
    if request.method == "POST":
        marks = {s.id: request.POST.get(f"s{s.id}", "present") for s in students}
        lesson.record_attendance(with_reasons(lesson, marks))
        _apply_lesson_record(lesson, request.POST, request.FILES)
        if lesson.completed and "submit" in request.POST:
            messages.success(request, _("Attendance submitted. Lesson marked Completed."))
            return redirect(f"/teacher/?d={lesson.date}")
        messages.success(request, _("Draft saved."))
        return redirect(request.path)
    shown = {"unexplained": "absent", "excused": "absent", "not_marked": "present"}
    current = {a.student_id: shown.get(a.status, a.status) for a in lesson.att.all()}
    times = lesson.att.aggregate(recorded=Max("recorded_at"), synced=Max("synced_at"))
    rows = [
        (s, current.get(s.id, ("late" if reported[s.id].kind == "late" else "absent") if s.id in reported else "present"), reported.get(s.id))
        for s in students
    ]
    return render(
        request,
        "tch.html",
        {"page": "form", "l": lesson, "opts": LESSON_STATUSES, "rows": rows, "times": times},
    )


@require_POST
@role_required("teacher")
def sync_attendance(request):
    """NFR-03: receive one lesson recorded offline as a single batch."""
    try:
        data = json.loads(request.body)
        lesson = Lesson.objects.get(pk=data["lesson"])
        marks = {int(k): v for k, v in data["marks"].items()}
        recorded_at = parse_datetime(data["recorded_at"])
    except (ValueError, KeyError, TypeError, Lesson.DoesNotExist):
        return JsonResponse({"ok": False, "error": _("The batch is incomplete.")}, status=400)
    if not lesson.taught_by(request.user):
        return JsonResponse({"ok": False, "error": _("Not your lesson.")}, status=403)
    if any(status not in LESSON_STATUSES for status in marks.values()):
        return JsonResponse({"ok": False, "error": _("The batch is incomplete.")}, status=400)
    try:
        with transaction.atomic():
            lesson.record_attendance(with_reasons(lesson, marks), recorded_at=recorded_at)
            _apply_lesson_record(lesson, data)
    except ValueError:
        return JsonResponse(
            {
                "ok": False,
                "error": _(
                    "The group list changed while you were offline. "
                    "Open the lesson again and re-check attendance."
                ),
            },
            status=409,
        )
    return JsonResponse(
        {
            "ok": True,
            "recorded_at": timezone.localtime(recorded_at).strftime("%d.%m.%Y %H:%M"),
            "synced_at": timezone.localtime().strftime("%d.%m.%Y %H:%M"),
        }
    )


def service_worker(request):
    """Caches teacher pages so the lesson form opens without internet."""
    response = HttpResponse(
        render_to_string("sw.js"), content_type="application/javascript"
    )
    response["Service-Worker-Allowed"] = "/"
    return response


@role_required("teacher")
def leave(request):
    post = request.POST
    if request.method == "POST":
        try:
            start = dt.date.fromisoformat(post["start"])
            end = dt.date.fromisoformat(post["end"])
        except (ValueError, KeyError):
            start = end = None
        if not start or end < start:
            messages.error(request, _("Enter a valid start and end date."))
        else:
            LeaveRequest.objects.create(
                teacher=request.user,
                start=start,
                end=end,
                reason=post.get("reason", "Sick leave"),
                note=post.get("note", ""),
                attachment=request.FILES.get("file") or "",
            )
            messages.success(request, _("Request submitted. Status: Pending."))
            return redirect("leave")
    requests = [
        (req, Lesson.objects.filter(group__teacher=request.user, date__range=[req.start, req.end]).count())
        for req in request.user.leaves.all()
    ]
    return render(request, "tch.html", {"page": "leave", "reqs": requests})
