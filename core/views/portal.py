"""Parent / student portal (FR-03 absence reporting, FR-05 personal account)."""

import datetime as dt
from functools import wraps

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from ..models import AbsenceReason, AbsenceReport, Attendance, Group, Lesson, Notification
from .common import role_required

ABSENCE_REASONS = AbsenceReason.values
LATE_MINUTES = (5, 10, 15, 30, 60)


def with_student(view):
    """Resolve the student shown in the portal: the student themself or the
    child the parent selected."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user, role = request.user, request.session["role"]
        if role == "student" and hasattr(user, "student"):
            student = user.student
        else:
            student = user.children.filter(pk=request.session.get("child")).first()
        if not student:
            return redirect("children" if role == "parent" else "login")
        return view(request, student, *args, **kwargs)

    return role_required("parent", "student")(wrapper)


def upcoming_lessons(student):
    lessons = Lesson.objects.filter(
        group=student.group, cancelled=False, date__gte=timezone.localdate()
    )
    return [lesson for lesson in lessons if not lesson.has_started()]


def reported_lessons(student):
    return set(
        AbsenceReport.objects.filter(student=student, withdrawn=False).values_list(
            "lesson_id", flat=True
        )
    )


def course_names():
    return Group.objects.exclude(course="").values_list("course", flat=True).distinct()


@role_required("parent")
def children(request):
    kids = request.user.children.select_related("group")
    if request.method == "POST":
        request.session["child"] = get_object_or_404(kids, pk=request.POST["child"]).pk
        return redirect("dash")
    return render(request, "fam.html", {"page": "children", "kids": kids})


@with_student
def dash(request, student):
    from .academic import lesson_state
    upcoming = upcoming_lessons(student) if student.group else []
    reported = reported_lessons(student)
    recent = list(student.attendance.exclude(status="not_marked").select_related("lesson").order_by("-lesson__date")[:5])[::-1]
    graded = list(student.assessments.filter(score__isnull=False)[:2])
    pay = student.payment_summary()
    charges = student.charges.order_by("-month")[:3]
    paid_months = {p.month for p in student.payments.all()}
    kids = request.user.children.select_related("group") if request.session["role"] == "parent" else []
    materials = Lesson.objects.filter(group=student.group, date__lte=timezone.localdate()).exclude(topic="").order_by("-date")[:3]
    notes = Notification.objects.filter(user=request.user).order_by("-created")[:3]
    if not notes and student.parent:
        notes = Notification.objects.filter(user=student.parent).order_by("-created")[:3]
    homework = Lesson.objects.filter(group=student.group).exclude(homework="").order_by("-date").first()
    return render(
        request,
        "fam.html",
        {
            "page": "dash", "s": student, "kids": kids,
            "nl": upcoming[0] if upcoming else None, "next3": [(l, lesson_state(l), l.pk in reported) for l in upcoming[:3]],
            "pct": student.attendance_pct(), "recent": recent,
            "latest": graded[0] if graded else None, "prev": graded[1] if len(graded) > 1 else None,
            "delta": graded[0].score - graded[1].score if len(graded) > 1 else None,
            "pay": pay, "charges": [(c, c.month in paid_months) for c in charges],
            "last_payment": student.payments.order_by("-paid_on").first(),
            "materials": materials, "notes": notes, "homework": homework,
            "reasons": ABSENCE_REASONS, "upcoming": upcoming[:6],
        },
    )


@with_student
def fschedule(request, student):
    week = int(request.GET.get("w", 0))
    today = timezone.localdate()
    monday = today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=week)
    lessons = Lesson.objects.filter(
        group=student.group, date__range=[monday, monday + dt.timedelta(days=6)]
    ).select_related("group__teacher", "substitute")
    return render(
        request,
        "fam.html",
        {
            "page": "schedule",
            "s": student,
            "ls": lessons,
            "w": week,
            "mon": monday,
            "rep": reported_lessons(student),
            "now": timezone.now(),
        },
    )


@with_student
def absence(request, student):
    """FR-03 in three steps: 1 choose a lesson, 2 absence details, 3 confirmation."""
    error, post = "", request.POST
    lessons = Lesson.objects.filter(group=student.group, cancelled=False, date__gte=timezone.localdate() - dt.timedelta(days=1))
    if request.method == "POST" and post.get("act") == "withdraw":
        report = get_object_or_404(AbsenceReport, pk=post["report"], student=student)
        report.withdraw()
        Notification.send(report.lesson.teacher_on_duty, "absence", f"{student.name}: absence report for {report.lesson.date:%d.%m} withdrawn.")
        return redirect(f"{request.path}?done={report.pk}")
    if request.method == "POST":
        lesson = get_object_or_404(Lesson, pk=post["lesson"], group=student.group)
        reason, kind = post.get("reason"), post.get("kind", "absent")
        if lesson.has_started():
            error = _("The lesson has already started. Please call the administrator: +998 90 000 10 10.")
        elif reason not in ABSENCE_REASONS:
            error = _("Choose a reason.")
        elif reason == "Other" and not post.get("note"):
            error = _("Please add a short note for Other.")
        else:
            until = None
            if post.get("until"):
                until = min(dt.date.fromisoformat(post["until"]), lesson.date + dt.timedelta(days=13))
            minutes = int(post["minutes"]) if kind == "late" and post.get("minutes", "").isdigit() else None
            targets = [lesson] + (list(lessons.filter(date__gt=lesson.date, date__lte=until)) if until and kind == "absent" else [])
            first = None
            for l in targets:
                report, _created = AbsenceReport.objects.update_or_create(
                    student=student, lesson=l,
                    defaults={"kind": kind, "reason": reason, "note": post.get("note", ""), "minutes": minutes,
                              "until": until, "withdrawn": False},
                )
                first = first or report
            what = f"late by {minutes} min" if kind == "late" else "absence"
            Notification.send(
                lesson.teacher_on_duty, "absence",
                f"{student.name}: {what} reported for {lesson.date:%d.%m.%Y} {lesson.start:%H:%M} ({reason}).",
            )
            messages.success(request, _("Absence reported. The lesson now shows Reported."))
            return redirect(f"{request.path}?done={first.pk}")
    done = AbsenceReport.objects.filter(pk=request.GET.get("done"), student=student).select_related("lesson__group").first()
    chosen = None
    if request.GET.get("lesson") or request.method == "POST":
        chosen = lessons.filter(pk=post.get("lesson") or request.GET.get("lesson")).first()
    step = 3 if done else 2 if chosen else 1
    started = chosen.has_started() if chosen else False
    return render(
        request,
        "absence.html",
        {
            "s": student, "step": step, "done": done, "l": chosen, "started": started, "err": error,
            "ls": [(l, l.has_started(), l.pk in reported_lessons(student)) for l in lessons[:8]],
            "reasons": ABSENCE_REASONS, "minutes": LATE_MINUTES, "post": post,
            "max_until": (chosen.date + dt.timedelta(days=13)) if chosen else None,
        },
    )


@with_student
def attendance(request, student):
    f = request.GET
    rows = (
        Attendance.objects.filter(student=student)
        .exclude(status="not_marked")
        .select_related("lesson__group")
    )
    if f.get("from"):
        rows = rows.filter(lesson__date__gte=f["from"])
    if f.get("to"):
        rows = rows.filter(lesson__date__lte=f["to"])
    if f.get("subject"):
        rows = rows.filter(lesson__group__course=f["subject"])
    total = rows.count()
    attended = rows.exclude(status__in=["absent", "unexplained"]).count()
    return render(
        request,
        "fam.html",
        {
            "page": "attendance",
            "s": student,
            "rows": rows.order_by("-lesson__date"),
            "pct": round(100 * attended / total) if total else 100,
            "rep": reported_lessons(student),
            "subjects": course_names(),
            "g": f,
        },
    )


@with_student
def grades(request, student):
    rows = student.assessments.all()
    if request.GET.get("subject"):
        rows = rows.filter(subject=request.GET["subject"])
    subjects = student.assessments.values_list("subject", flat=True).distinct()
    return render(
        request,
        "fam.html",
        {"page": "grades", "s": student, "rows": rows, "subjects": subjects, "g": request.GET},
    )


@with_student
def materials(request, student):
    f = request.GET
    rows = (
        Lesson.objects.filter(group=student.group, date__lte=timezone.localdate())
        .exclude(topic="")
        .select_related("group")
    )
    if f.get("subject"):
        rows = rows.filter(group__course=f["subject"])
    if f.get("q"):
        rows = rows.filter(topic__icontains=f["q"])
    return render(
        request,
        "fam.html",
        {
            "page": "materials",
            "s": student,
            "rows": rows.order_by("-date"),
            "subjects": course_names(),
            "g": f,
        },
    )


@with_student
def payments(request, student):
    return render(
        request,
        "fam.html",
        {
            "page": "payments",
            "s": student,
            "pay": student.payment_summary(),
            "rows": student.payments.order_by("-created"),
        },
    )