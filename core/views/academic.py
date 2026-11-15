"""Groups, timetable, substitutions, certificates and the management overview."""

import datetime as dt

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from ..models import (
    AbsenceReport,
    Applicant,
    Charge,
    Attendance,
    Branch,
    Certificate,
    Group,
    LeaveRequest,
    Lesson,
    Notification,
    Payment,
    Student,
    User,
)
from .common import STAFF, role_required

ATTENDANCE_OPTIONS = ["present", "late", "excused", "unexplained", "not_marked"]
ROOMS = ["204", "205", "101"]


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def is_makeup(lesson):
    days = lesson.group.schedule.split("·")[0]
    return WEEKDAYS[lesson.date.weekday()] not in days if lesson.date.weekday() < 5 else True


@role_required(*STAFF, "teacher")
def schedule(request):
    today = timezone.localdate()
    week = int(request.GET.get("w", 0))
    monday = today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=week)
    lessons = Lesson.objects.filter(date__range=[monday, monday + dt.timedelta(days=4)]).select_related("group__teacher", "substitute")
    is_teacher = request.session["role"] == "teacher"
    if is_teacher:
        lessons = lessons.filter(Q(group__teacher=request.user) | Q(substitute=request.user))
    teacher_f, room_f = request.GET.get("teacher", ""), request.GET.get("room", "")
    if teacher_f:
        lessons = lessons.filter(group__teacher_id=teacher_f)
    if room_f:
        lessons = lessons.filter(room=room_f)
    selected = None
    if request.GET.get("lesson"):
        selected = get_object_or_404(Lesson.objects.select_related("group"), pk=request.GET["lesson"])
    elif lessons:
        # open the lesson that most needs attention: most unexplained absences, then today's first lesson
        def issues(l):
            return l.att.filter(status="unexplained").count()
        selected = max(lessons, key=lambda l: (issues(l), l.date == today), default=None)

    if selected and request.method == "POST":
        students = selected.group.students.all()
        for s in students:
            key = f"s{s.id}"
            if key in request.POST:
                Attendance.objects.update_or_create(
                    lesson=selected, student=s,
                    defaults={"status": request.POST[key], "recorded_at": timezone.now(), "synced_at": timezone.now()},
                )
        if "notify" in request.POST:
            absent = students.filter(attendance__lesson=selected, attendance__status="unexplained", parent__isnull=False)
            for s in absent:
                Notification.send(s.parent, "attendance", f"{s.name} was marked absent without a reason in {selected.group.name}.")
            messages.success(request, _("Parents of students with unexplained absences were notified."))
        else:
            messages.success(request, _("Attendance saved."))
        return redirect(f"{request.path}?lesson={selected.pk}&w={week}")

    # weekly grid: rows = start times, columns = Mon..Fri
    slots = sorted({l.start for l in lessons})
    days = [monday + dt.timedelta(days=i) for i in range(5)]
    grid = []
    for t in slots:
        cells = []
        for d in days:
            items = []
            for l in lessons:
                if l.date == d and l.start == t:
                    tag = ""
                    if l.cancelled:
                        tag = "Cancelled"
                    elif l.needs_sub and not l.substitute_id:
                        tag = "Cover pending"
                    elif l.clash():
                        tag = "Room conflict"
                    elif is_makeup(l):
                        tag = "Make-up"
                    items.append((l, tag))
            cells.append(items)
        grid.append((t, cells))
    rows, counts = [], {}
    reported = {}
    if selected:
        marks = {a.student_id: a.status for a in selected.att.all()}
        reported = {r.student_id: r for r in AbsenceReport.objects.filter(lesson=selected, withdrawn=False)}
        for s in selected.group.students.all():
            st = marks.get(s.id, "excused" if s.id in reported else "not_marked")
            rows.append((s, st, reported.get(s.id)))
            counts[st] = counts.get(st, 0) + 1
    leave = LeaveRequest.objects.filter(status="Pending").select_related("teacher").first()
    conflict = next(((l, l.clash()) for l in lessons if not l.cancelled and l.clash()), None)
    return render(
        request,
        "schedule.html",
        {
            "grid": grid, "days": days, "today": today, "w": week, "monday": monday, "friday": days[-1],
            "sel": selected, "rows": rows, "counts": counts, "opts": ATTENDANCE_OPTIONS,
            "clash": selected.clash() if selected else None, "is_teacher": is_teacher,
            "teachers": User.objects.filter(roles__role="teacher"), "rooms": sorted(set(Lesson.objects.values_list("room", flat=True))),
            "teacher_f": teacher_f, "room_f": room_f, "leave": leave, "conflict": conflict,
            "unexplained_n": counts.get("unexplained", 0), "total_n": lessons.count(),
        },
    )


@role_required(*STAFF)
def substitute(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    candidates = User.objects.filter(roles__role="teacher").exclude(pk=lesson.group.teacher_id)
    room = request.POST.get("room") or request.GET.get("room") or lesson.room
    clash = lesson.clash(room)
    if request.method == "POST":
        text = None
        when = f"{lesson.date:%d.%m.%Y} {lesson.start:%H:%M}"
        if "cancel" in request.POST:
            lesson.cancelled = True
            text = f"Your child’s {lesson.group.name} lesson on {when} is cancelled."
        elif clash:
            messages.error(
                request,
                _("Room %(room)s is already booked (%(group)s). Choose another room.")
                % {"room": room, "group": clash.group.name},
            )
        else:
            lesson.substitute_id = request.POST["sub"]
            lesson.room = room
            text = f"Your child’s {lesson.group.name} lesson on {when} changed: Room {room}."
        if text:
            lesson.save()
            lesson.group.notify_parents("schedule", text)
            messages.success(request, _("Confirmed. Parents of this lesson were notified."))
            return redirect("schedule")
    def busy(u):
        return Lesson.objects.filter(
            Q(group__teacher=u) | Q(substitute=u), date=lesson.date, cancelled=False,
            start__lt=lesson.end, end__gt=lesson.start,
        ).exclude(pk=lesson.pk).exists()

    options = [(u, busy(u)) for u in candidates]
    free_rooms = [r for r in ROOMS if not lesson.clash(r)]
    return render(
        request,
        "substitute.html",
        {"l": lesson, "subs": options, "room": room, "clash": clash, "rooms": ROOMS, "free_rooms": free_rooms,
         "families": lesson.group.students.filter(parent__isnull=False).count()},
    )


@role_required(*STAFF)
def groups(request):
    is_admin = request.session["role"] == "admin"
    post = request.POST
    if request.method == "POST" and is_admin:
        return _group_action(request, post)
    status, query = request.GET.get("s", "active"), request.GET.get("q", "")
    found = Group.objects.filter(name__icontains=query).select_related("teacher")
    if status != "all":
        found = found.filter(status=status) if status != "inactive" else found.exclude(status="active")
    selected = Group.objects.filter(pk=request.GET.get("g")).first() or found.first()
    active = Group.objects.filter(active=True)
    places = sum(g.capacity for g in active)
    enrolled = sum(g.enrolled for g in active)
    members = []
    if selected:
        members = [(s, s.attendance_pct(), s.payment_summary()) for s in selected.students.all()]
    leave = LeaveRequest.objects.filter(status="Pending", teacher=selected.teacher).first() if selected and selected.teacher else None
    waiting = Applicant.objects.filter(waiting=True)
    return render(
        request,
        "groups.html",
        {
            "sts": [("active", "Active"), ("inactive", "Inactive"), ("all", "All")],
            "counts": {"active": Group.objects.filter(status="active").count(), "inactive": Group.objects.exclude(status="active").count(),
                       "all": Group.objects.count()},
            "gs": found, "sel": selected, "st": status, "q": query, "adm": is_admin,
            "teachers": User.objects.filter(roles__role="teacher"),
            "cands": Applicant.objects.filter(contract_recorded=True).exclude(stage="Confirmed"),
            "subs": Lesson.objects.filter(group=selected, needs_sub=True, substitute__isnull=True) if selected else [],
            "waiting": waiting, "leaves": LeaveRequest.objects.filter(status="Pending").select_related("teacher"),
            "members": members, "leave": leave,
            "n_active": active.count(), "n_archived": Group.objects.exclude(status="active").count(),
            "enrolled": enrolled, "subjects_n": active.values("course").distinct().count(),
            "free": places - enrolled, "places": places, "util": round(100 * enrolled / places) if places else 0,
            "inactive": Group.objects.exclude(status="active").select_related("teacher")[:3],
            "full_groups": [g for g in active if not g.has_place()],
        },
    )


def _group_action(request, post):
    act = post["act"]
    if act == "create":
        group = Group.objects.create(
            name=post.get("name") or "New group",
            branch=Branch.objects.first(),
            course=post.get("course", ""),
            level=post.get("level", ""),
            capacity=int(post.get("capacity") or 12),
        )
        messages.success(request, _("Group created."))
        return redirect(f"/groups/?g={group.pk}")
    if act == "leave":
        req = get_object_or_404(LeaveRequest, pk=post["req"])
        req.decide(approve=post["d"] == "approve")
        messages.success(request, _("Request approved.") if req.status == "Approved" else _("Request rejected."))
        return redirect("groups")

    group = get_object_or_404(Group, pk=post["g"])
    if act == "save":
        group.name = post["name"]
        group.schedule = post.get("schedule", "")
        group.capacity = int(post.get("capacity") or group.capacity)
        group.teacher_id = post.get("teacher") or None
        group.save()
        messages.success(request, _("Group saved."))
    elif act == "add":
        applicant = get_object_or_404(Applicant, pk=post["applicant"])
        error = applicant.join_group(group)
        if error:
            messages.error(request, _(error))
        else:
            messages.success(request, _("%(name)s added.") % {"name": applicant.name})
    elif act == "sub":
        lesson = get_object_or_404(Lesson, pk=post["lesson"], group=group)
        lesson.substitute_id = post["teacher"]
        lesson.needs_sub = False
        lesson.save()
        group.notify_parents(
            "schedule", f"{group.name} on {lesson.date:%d.%m.%Y}: substitute teacher assigned."
        )
        messages.success(request, _("Substitute assigned. It now shows in teacher and family schedules."))
    elif act in ("close", "archive"):
        group.close(archive=act == "archive")
        messages.success(request, _("Group %(status)s.") % {"status": _(group.status)})
        return redirect("groups")
    return redirect(f"/groups/?g={group.pk}")


@role_required("teacher", *STAFF)
def reports(request):
    is_teacher = request.session["role"] == "teacher"
    certificates = Certificate.objects.select_related("student", "group")
    if is_teacher:
        certificates = certificates.filter(group__teacher=request.user)
    if request.method == "POST":
        cert = get_object_or_404(certificates, pk=request.POST["cert"])
        act = request.POST["act"]
        if is_teacher and act == "submit":
            cert.submit()
        elif not is_teacher:
            cert.decide(act)
        return redirect("reports")
    return render(request, "reports.html", {"cs": certificates, "teacher": is_teacher})


def teaching_day(qs=None):
    """Today, or the next day that has lessons (the overview is useful on weekends too)."""
    qs = qs if qs is not None else Lesson.objects.all()
    today = timezone.localdate()
    nxt = qs.filter(date__gte=today, cancelled=False).order_by("date").values_list("date", flat=True).first()
    return nxt or today


def lesson_state(lesson, now=None):
    now = now or timezone.now()
    end = timezone.make_aware(dt.datetime.combine(lesson.date, lesson.end))
    if lesson.cancelled:
        return "Cancelled"
    if lesson.completed:
        return "Completed"
    if lesson.needs_sub and not lesson.substitute_id:
        return "Cover pending"
    if end <= now:
        return "Attendance due"
    if lesson.start_dt <= now:
        return "In progress"
    return "Upcoming"


def weekly_attendance(weeks=5, group=None):
    today = timezone.localdate()
    monday = today - dt.timedelta(days=today.weekday())
    out = []
    for k in range(weeks - 1, -1, -1):
        start = monday - dt.timedelta(weeks=k)
        qs = Attendance.objects.filter(lesson__date__range=[start, start + dt.timedelta(days=6)]).exclude(status="not_marked")
        if group:
            qs = qs.filter(lesson__group=group)
        n = qs.count()
        ok = qs.exclude(status__in=["absent", "unexplained"]).count()
        out.append((start, round(100 * ok / n, 1) if n else None))
    return [(d, v) for d, v in out if v is not None]


def monthly_collections(months=6):
    today = timezone.localdate()
    out = []
    for k in range(months - 1, -1, -1):
        y, m = today.year, today.month - k
        while m <= 0:
            m += 12
            y -= 1
        first = dt.date(y, m, 1)
        out.append((first, sum(p.amount for p in Payment.objects.filter(month=first))))
    return out


@role_required(*STAFF)
def overview(request):
    today = timezone.localdate()
    month = today.replace(day=1)
    start = request.GET.get("from") or month.isoformat()
    end = request.GET.get("to") or today.isoformat()
    active_groups = Group.objects.filter(active=True)
    capacity = sum(g.capacity for g in active_groups)
    enrolled = sum(g.enrolled for g in active_groups)
    collected = sum(p.amount for p in Payment.objects.filter(month=month))
    scheduled = sum(c.amount for c in Charge.objects.filter(month=month))

    day = teaching_day()
    lessons = Lesson.objects.filter(date=day).select_related("group__teacher", "substitute").order_by("start")
    rows = [(l, lesson_state(l)) for l in lessons]

    week_ago = today - dt.timedelta(days=7)
    unexplained = Attendance.objects.filter(status="unexplained", lesson__date__gte=week_ago).select_related("student", "lesson__group")
    names = sorted({a.student.name for a in unexplained})
    pending = Applicant.objects.filter(stage__in=["Agreement", "Trial completed"])
    cover = Lesson.objects.filter(needs_sub=True, substitute__isnull=True, cancelled=False, date__gte=today).select_related("group__teacher").first()
    leave = LeaveRequest.objects.filter(status="Pending").select_related("teacher").first()
    attention = []
    if names:
        attention.append({"icon": "users", "title": _("%(n)s unexplained absences") % {"n": len(names)},
                          "sub": ", ".join(names[:2]) + (" …" if len(names) > 2 else ""), "tag": "Parents not yet notified", "tone": "bad",
                          "link": "schedule", "action": "Notify parents"})
    if pending:
        attention.append({"icon": "file", "title": _("%(n)s enrolment decisions pending") % {"n": pending.count()},
                          "sub": pending.first().name + " · " + _(pending.first().stage), "tag": "Trial completed", "tone": "warn",
                          "link": "enrolment", "action": "Review applicants"})
    if cover or leave:
        who = cover.group.teacher.get_full_name() if cover else leave.teacher.get_full_name()
        when = f"{cover.date:%d.%m} · {cover.group.name}" if cover else f"{leave.start:%d.%m} → {leave.end:%d.%m}"
        attention.append({"icon": "clock", "title": _("Cover needed") + " · " + when, "sub": who, "tag": "Substitute required",
                          "tone": "pri", "link": "groups", "action": "Confirm substitute"})

    trend = weekly_attendance()
    money = monthly_collections()
    marked = Attendance.objects.filter(lesson__date__range=[start, end]).exclude(status="not_marked")
    total = marked.count()
    statuses = {s: marked.filter(status=s).count() for s in ("present", "late", "excused", "unexplained", "absent")}
    return render(
        request,
        "overview.html",
        {
            "f": start, "t": end, "today": today, "day": day,
            "students": Student.objects.filter(active=True).count(),
            "groups_n": active_groups.count(),
            "subjects_n": active_groups.values("course").distinct().count(),
            "teachers_n": active_groups.values("teacher").distinct().count(),
            "util": round(100 * enrolled / capacity) if capacity else 0, "enrolled": enrolled, "capacity": capacity,
            "collected": collected, "scheduled": scheduled,
            "rows": rows, "attention": attention,
            "trend_vals": [v for _, v in trend], "trend_labels": ",".join(f"{d:%d.%m}" for d, _ in trend),
            "money_now": money[-1][1] if money else 0,
            "trend_now": trend[-1][1] if trend else 0,
            "trend_delta": round(trend[-1][1] - trend[-2][1], 1) if len(trend) > 1 else 0,
            "money_vals": [v / 1_000_000 for _, v in money], "money_labels": ",".join(date_format(d, "M") for d, _ in money),
            "money_delta": round(100 * (money[-1][1] - money[-2][1]) / money[-2][1], 1) if len(money) > 1 and money[-2][1] else 0,
            "rate": round(100 * (total - statuses["unexplained"] - statuses["absent"]) / total, 1) if total else 100,
            "st": {k: round(100 * v / total, 1) if total else 0 for k, v in statuses.items()},
            "over": sum(i["owed"] for i in (s.payment_summary() for s in Student.objects.all()) if i["status"] == "Overdue"),
            "pay_ok": request.session["role"] in ("admin", "director"),
            "spark": [g.enrolled for g in active_groups],
        },
    )
