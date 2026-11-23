import json
from collections import defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import Group as AuthGroup, User
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_POST

from . import finance
from .forms import ApplicantForm, GroupForm, LessonForm
from .models import *
from .notify import notify
from .roles import VIEW_PEOPLE, role, role_required
from .scheduling import room_clash, teacher_clash, week_conflicts

STAFF = ("admin",)
MAX_SCAN = 10 * 1024 * 1024


def when(dt):
    return timezone.localtime(dt).strftime("%d.%m %H:%M")


def monday(d):
    return d - timedelta(days=d.weekday())


def service_worker(request):
    js = """
const C='itmatic-v3';
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(C).then(c=>c.addAll(['/static/core/style.css','/static/core/app.js','/static/core/offline.js','/static/core/attendance.js']).catch(()=>{})));});
self.addEventListener('activate',e=>e.waitUntil(clients.claim()));
self.addEventListener('fetch',e=>{
  const r=e.request; if(r.method!=='GET'||new URL(r.url).origin!==location.origin) return;
  e.respondWith(fetch(r).then(res=>{const c=res.clone();caches.open(C).then(x=>x.put(r,c));return res;})
    .catch(()=>caches.match(r)));
});"""
    return HttpResponse(js, content_type="application/javascript")


# ================================================================ overview
def waiting_ready():
    rows = (Applicant.objects.filter(status="waiting")
            .values("course", "course__name", "level", "kind").annotate(n=Count("id")))
    return [r for r in rows if r["n"] >= settings.WAITLIST_MIN.get(r["kind"], 99)]


def missing_qs():
    return Lesson.objects.filter(status="scheduled", attendance_saved_at__isnull=True,
                                 start__lt=timezone.now() - timedelta(minutes=settings.ATTENDANCE_OVERDUE_MIN))


def cover_needed():
    """Future lessons whose teacher is registered absent and that have neither a substitute nor a cancellation."""
    out = []
    for ab in TeacherAbsence.objects.filter(end_date__gte=timezone.localdate()).select_related("teacher"):
        out += list(Lesson.objects.filter(group__teacher=ab.teacher, status="scheduled", substitute__isnull=True,
                    start__date__gte=max(ab.start_date, timezone.localdate()), start__date__lte=ab.end_date)
                    .select_related("group", "group__teacher"))
    return sorted(out, key=lambda l: l.start)


def attendance_trend(weeks=5):
    this = monday(timezone.localdate())
    rows = []
    for i in range(weeks - 1, -1, -1):
        a = this - timedelta(weeks=i)
        qs = Attendance.objects.filter(lesson__start__date__gte=a, lesson__start__date__lt=a + timedelta(days=7))
        n = qs.count()
        ok = qs.exclude(status="absent").count()
        rows.append({"label": a.strftime("%d.%m"), "n": n, "pct": round(100 * ok / n) if n else None})
    return rows


def collections(months=6):
    t = timezone.localdate().replace(day=1)
    rows = []
    for i in range(months - 1, -1, -1):
        y, m = t.year, t.month - i
        while m <= 0:
            y, m = y - 1, m + 12
        a = t.replace(year=y, month=m)
        b = (a.replace(day=28) + timedelta(days=4)).replace(day=1)
        tot = Payment.objects.filter(created_at__date__gte=a, created_at__date__lt=b).aggregate(s=Sum("amount"))["s"] or 0
        rows.append({"label": a.strftime("%b"), "sum": tot})
    mx = max([r["sum"] for r in rows] + [1])
    for r in rows:
        r["h"] = round(100 * r["sum"] / mx)
    return rows


def dashboard(request):
    if not request.user.is_authenticated:
        return redirect("login_phone")
    r = role(request.user)
    if r is None:
        return redirect("select_role")
    if r in ("parent", "student"):
        return redirect("records")
    today, now = timezone.localdate(), timezone.now()
    c = {"today": today}
    month_start = today.replace(day=1)
    if r in STAFF:
        groups = Group.objects.all()
        seats = sum(g.capacity for g in groups)
        students = Student.objects.filter(active=True).count()
        c.update(students=students, groups_n=groups.count(), seats=seats, util=round(100 * students / seats) if seats else 0,
                 teachers_n=User.objects.filter(groups__name="teacher").count(),
                 collected=Payment.objects.filter(created_at__date__gte=month_start).aggregate(s=Sum("amount"))["s"] or 0,
                 scheduled=Fee.objects.filter(month=month_start).aggregate(s=Sum("amount"))["s"] or 0,
                 lessons=Lesson.objects.filter(start__date=today).select_related("group", "room", "substitute", "group__teacher"),
                 pending_apps=Applicant.objects.filter(status="in_progress").count(),
                 cover=cover_needed()[:5], missing=missing_qs().count(), ready=waiting_ready(),
                 trend=attendance_trend(), money=collections())
        c["collected_pct"] = round(100 * c["collected"] / c["scheduled"]) if c["scheduled"] else 0
        c["deciding"] = [a for a in Applicant.objects.filter(status="in_progress").select_related("course") if a.stage >= 5][:5]
        c["pending_discounts"] = DiscountRequest.objects.filter(status="pending").count()
    elif r == "accountant":
        c.update(debt=sum(x["due"] for x in finance.debtors(today)), money=collections(),
                 paid_today=Payment.objects.filter(created_at__date=today).aggregate(s=Sum("amount"))["s"] or 0,
                 collected=Payment.objects.filter(created_at__date__gte=month_start).aggregate(s=Sum("amount"))["s"] or 0,
                 pending_discounts=DiscountRequest.objects.filter(status="pending").count())
    elif r == "teacher":
        mine = Lesson.objects.filter(Q(substitute=request.user) | Q(substitute__isnull=True, group__teacher=request.user))
        c.update(lessons=mine.filter(start__date=today).select_related("group", "room"),
                 upcoming=mine.filter(start__date__gt=today, start__date__lte=today + timedelta(days=7)).select_related("group", "room")[:8],
                 my_groups=Group.objects.filter(teacher=request.user), to_meet=_teacher_applicants(request.user).filter(status="in_progress", conversation_result="")[:5])
    return render(request, "dashboard.html", c)


def global_search(request):
    if role(request.user) not in STAFF + ("admin", "accountant", "teacher"):
        raise PermissionDenied
    q = request.GET.get("q", "").strip()
    studs, grps, apps = [], [], []
    if q:
        studs = Student.objects.filter(Q(name__icontains=q) | Q(parent__profile__phone__icontains=q.replace("+", "")))
        grps = Group.objects.filter(name__icontains=q)
        if role(request.user) == "teacher":                       # NFR-01: scope first, slice last
            studs = studs.filter(group__teacher=request.user); grps = grps.filter(teacher=request.user)
        studs = studs.select_related("group")[:20]; grps = grps[:10]
        apps = Applicant.objects.filter(Q(name__icontains=q) | Q(parent_phone__icontains=q))[:10] if role(request.user) in STAFF else []
    return render(request, "search.html", {"q": q, "studs": studs, "grps": grps, "apps": apps})


@role_required("parent", "student", *STAFF, "accountant", "teacher")
def notifications(request):
    items = list(request.user.notifications.all()[:60])
    request.user.notifications.filter(read=False).update(read=True)
    return render(request, "notifications.html", {"items": items})


# ================================================================ UC-1 / FR-01 enrolment
def level_for(score):
    return "beginner" if score < 25 else "elementary" if score < 50 else "intermediate" if score < 75 else "advanced"


def _teacher_applicants(user):
    courses = Group.objects.filter(teacher=user).values_list("course_id", flat=True)
    return Applicant.objects.filter(course_id__in=courses)


@role_required("admin", "teacher")
def applicants(request):
    qs = Applicant.objects.select_related("course", "branch")
    if role(request.user) == "teacher":
        qs = _teacher_applicants(request.user).select_related("course", "branch")
    status, q = request.GET.get("status"), request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(parent_phone__icontains=q))
    scope = Applicant.objects.all() if role(request.user) == "admin" else _teacher_applicants(request.user)
    counts = dict(scope.values_list("status").annotate(n=Count("id")))      # counters follow the same scope as the list (NFR-01)
    return render(request, "applicants.html", {"items": qs[:200], "status": status, "q": q, "statuses": Applicant.STATUS,
                  "counts": counts, "ready": waiting_ready() if role(request.user) == "admin" else []})


@role_required("admin")
def applicant_new(request):
    form = ApplicantForm(request.POST or None)
    if form.is_valid():
        return redirect("applicant_detail", form.save().pk)
    return render(request, "form.html", {"form": form, "title": "New enquiry", "back": "applicants"})


def _account(group_name, username, name, phone, reuse):
    ph = normalize_phone(phone)
    prof = Profile.objects.filter(phone=ph).select_related("user").first() if ph else None
    if prof and reuse:
        u = prof.user
        g = AuthGroup.objects.get_or_create(name=group_name)[0]
        u.groups.add(g)                                   # a person can hold several roles under one phone
        return u
    if prof:
        ph = None
    if reuse:
        u = User.objects.filter(username=username).first()
        if u:
            u.groups.add(AuthGroup.objects.get_or_create(name=group_name)[0])
            return u
    else:
        while User.objects.filter(username=username).exists():     # never reuse another person's login name
            username += "x"
    u = User.objects.create_user(username, first_name=name)
    u.set_unusable_password(); u.save()                   # UC-5: they sign in with phone + SMS
    u.groups.add(AuthGroup.objects.get_or_create(name=group_name)[0])
    Profile.objects.create(user=u, phone=ph)
    return u


def _valid_scan(f):
    return f.size <= MAX_SCAN and f.name.lower().rsplit(".", 1)[-1] in ("pdf", "jpg", "jpeg", "png")


@role_required("admin", "teacher")
def applicant_detail(request, pk):
    a = get_object_or_404(Applicant.objects.select_related("course", "group", "branch"), pk=pk)
    r = role(request.user)
    if r == "teacher" and not _teacher_applicants(request.user).filter(pk=pk).exists():
        raise PermissionDenied
    open_ = a.status in ("in_progress", "waiting")
    if request.method == "POST":
        act, P = request.POST.get("action"), request.POST
        if r == "teacher" and act != "conversation":
            raise PermissionDenied
        err = None
        if act == "start" and a.status == "new":
            a.status = "in_progress"
        elif act == "placement" and open_:
            if P.get("skip"):
                if not P.get("skip_reason", "").strip():
                    err = "A reason is required when the test is skipped"
                else:
                    a.placement_skipped, a.placement_score, a.level = True, None, "beginner"
                    a.skip_reason, a.test_date = P["skip_reason"].strip()[:200], None
            else:
                try:
                    sc = int(P.get("score", "")); assert 0 <= sc <= 100
                except (ValueError, AssertionError):
                    err = "Score must be 0-100"
                else:
                    a.placement_skipped, a.placement_score, a.skip_reason = False, sc, ""
                    a.test_date = parse_date(P.get("test_date", "")) or timezone.localdate()
                    a.level = P.get("level") if P.get("level") in dict(LEVELS) else level_for(sc)
            if a.status == "waiting" and not err:
                a.status = "in_progress"
        elif act == "conversation" and a.status == "in_progress" and a.placement_done and P.get("result") in dict(Applicant.CONV):
            a.conversation_result, a.conversation_note = P["result"], P.get("note", "").strip()
        elif act == "reset_conversation" and a.status == "in_progress":
            a.conversation_result = a.conversation_note = ""      # 4b: not suitable -> repeat with another teacher/group
            a.trial_attended, a.feedback = None, ""
        elif act == "trial" and a.status == "in_progress" and a.conversation_result == "accepted" and P.get("value") in ("yes", "no"):
            a.trial_attended = P["value"] == "yes"
            if not a.trial_attended:
                a.feedback = ""
        elif act == "feedback" and a.status == "in_progress" and a.trial_attended and P.get("value") in dict(Applicant.FEEDBACK):
            v = P["value"]
            if v == "another_group":                                # 5b: repeat conversation and trial
                a.conversation_result = a.conversation_note = a.feedback = ""
                a.trial_attended = None
                messages.info(request, "Conversation and trial lesson are reset - choose another group's teacher.")
            else:
                a.feedback = v
                if v == "declines":
                    messages.warning(request, "Applicant declines - record the reason below.")
        elif act == "prepare_contract" and open_:
            a.contract_prepared = True
            a.contract_number = a.contract_number or a.suggested_contract_number
        elif act == "contract" and a.status == "in_progress" and a.feedback == "wants_join":
            d, num, f = parse_date(P.get("date", "")), P.get("number", "").strip(), request.FILES.get("scan")
            if not (num and d):
                err = "Contract number and signing date are required"
            elif not (f or a.contract_scan):
                err = "Upload the signed scan (PDF / JPG / PNG)"
            elif f and not _valid_scan(f):
                err = "Scan must be PDF, JPG or PNG up to 10 MB"
            else:
                a.contract_number, a.contract_date, a.contract_prepared = num, d, True
                if f:
                    a.contract_scan = f
        elif act == "waitlist" and open_ and a.placement_done:
            a.status, a.group = "waiting", None
            a.save()
            n = Applicant.objects.filter(status="waiting", course=a.course, level=a.level, kind=a.kind).count()
            if n >= settings.WAITLIST_MIN.get(a.kind, 99):
                messages.warning(request, f"{n} applicants wait for {a.course} / {a.get_level_display()} ({a.get_kind_display()}) - create a group.")
        elif act == "lost" and open_:
            reason, note = P.get("reason"), P.get("note", "").strip()
            if reason not in dict(LOST_REASONS) or (reason == "other" and not note):
                err = "A refusal reason is mandatory"
            else:
                a.lost_reason, a.lost_note, a.follow_up, a.status = reason, note, True, "lost"
        elif act == "contacted" and a.status == "lost":
            a.follow_up = False
        elif act == "reopen" and a.status == "lost":
            a.status, a.follow_up, a.lost_reason, a.lost_note = "in_progress", False, "", ""
        elif act == "add_to_group" and a.status in ("in_progress", "waiting"):
            g = get_object_or_404(Group, pk=P.get("group"), course=a.course, level=a.level)
            if a.stage < 6:
                err = "This applicant cannot join a group until every stage is done and a signed contract is recorded."
            elif g.places_left <= 0:
                err = "Group is full"
            else:
                with transaction.atomic():
                    parent = _account("parent", f"p{normalize_phone(a.parent_phone)}", a.parent_name or "Parent of " + a.name, a.parent_phone, True)
                    su = _account("student", f"stu{a.pk}", a.name, a.phone, False)
                    s = Student.objects.create(user=su, parent=parent, name=a.name, group=g, applicant=a,
                                               contract_number=a.contract_number, contract_date=a.contract_date,
                                               contract_scan=a.contract_scan)
                    Fee.objects.get_or_create(student=s, month=timezone.localdate().replace(day=1), defaults={"amount": g.fee})
                    a.group, a.status = g, "completed"
                    notify(parent, "Student {student} was enrolled in group {group}", student=a.name, group=g.name)
                messages.success(request, "Student, parent account and first month fee created. They sign in with phone + SMS.")
        if err:
            messages.error(request, err)
        else:
            a.save()
        return redirect("applicant_detail", a.pk)
    groups = []
    if a.placement_done and a.status != "completed":
        groups = Group.objects.filter(course=a.course, level=a.level).select_related("teacher", "branch", "room")
        groups = [g for g in groups if g.places_left > 0]
    log = [("Enquiry received", f"{a.parent_name or 'Parent'} · {a.course}")]
    if a.placement_done:
        log.append(("Level test", "skipped" if a.placement_skipped else f"{a.get_level_display()} · {a.placement_score} / 100"))
    if a.conversation_result:
        log.append(("Teacher conversation", a.get_conversation_result_display()))
    if a.trial_attended is not None:
        log.append(("Free trial", "Attended" if a.trial_attended else "Did not attend"))
    if a.feedback:
        log.append(("Student feedback", a.get_feedback_display()))
    if a.contract_done:
        log.append(("Contract", f"{a.contract_number} · {a.contract_date:%d.%m.%Y}"))
    return render(request, "applicant_detail.html", {"a": a, "groups": groups, "levels": LEVELS, "reasons": LOST_REASONS,
                  "log": log, "today": timezone.localdate(), "can_edit": r == "admin", "is_teacher": r == "teacher"})


@role_required("admin")
def followup(request):
    items = Applicant.objects.filter(status="lost").select_related("course").order_by("-follow_up", "-created_at")
    return render(request, "followup.html", {"items": items})


# ================================================================ groups
@role_required(*STAFF, "teacher")
def groups(request):
    qs = Group.objects.select_related("course", "teacher", "room", "branch").annotate(n=Count("students", filter=Q(students__active=True)))
    if role(request.user) == "teacher":
        qs = qs.filter(teacher=request.user)
    return render(request, "groups.html", {"items": qs, "ready": waiting_ready() if role(request.user) != "teacher" else []})


@role_required("admin")
def group_new(request):
    initial = {k: request.GET[k] for k in ("course", "level", "kind") if k in request.GET}
    form = GroupForm(request.POST or None, initial=initial)
    if form.is_valid():
        g = form.save()
        n = Applicant.objects.filter(status="waiting", course=g.course, level=g.level, kind=g.kind).count()
        if n:
            messages.info(request, f"{n} waiting applicants match this group - assign them from their profiles.")
        return redirect("groups")
    return render(request, "form.html", {"form": form, "title": "New group", "back": "groups"})


@role_required(*STAFF, "teacher")
def group_detail(request, pk):
    g = get_object_or_404(Group.objects.select_related("course", "teacher", "room", "branch"), pk=pk)
    if role(request.user) == "teacher" and g.teacher_id != request.user.id:
        raise PermissionDenied
    studs = list(g.students.filter(active=True))
    for s in studs:
        a = Attendance.objects.filter(student=s, lesson__group=g)
        s.att_pct = round(100 * a.exclude(status="absent").count() / a.count()) if a.count() else None
    return render(request, "group_detail.html", {"g": g, "studs": studs, "waiting": Applicant.objects.filter(status="waiting", course=g.course, level=g.level, kind=g.kind).count()})



# ================================================================ schedule + UC-4 teacher absence
@role_required("admin")
def lesson_new(request):
    form = LessonForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, "Saved")
        return redirect("schedule")
    return render(request, "form.html", {"form": form, "title": "Schedule lesson", "back": "schedule"})


@role_required("admin", "teacher")
def schedule(request):
    r = role(request.user)
    d = parse_date(request.GET.get("week", "")) or timezone.localdate()
    mon = monday(d)
    days = [mon + timedelta(days=i) for i in range(6)]
    tid, rid = request.GET.get("teacher"), request.GET.get("room")
    qs = Lesson.objects.filter(start__date__gte=mon, start__date__lt=mon + timedelta(days=6)).select_related("group", "room", "substitute", "group__teacher")
    if r == "teacher":
        qs = qs.filter(Q(substitute=request.user) | Q(substitute__isnull=True, group__teacher=request.user))
    if tid:
        qs = qs.filter(Q(substitute_id=tid) | Q(substitute__isnull=True, group__teacher_id=tid))
    if rid:
        qs = qs.filter(room_id=rid)
    lessons = list(qs)
    bad = week_conflicts(lessons)
    cover = {l.id for l in cover_needed()}
    cells, times = defaultdict(list), set()
    for l in lessons:
        t = timezone.localtime(l.start)
        l.flag = "cancelled" if l.status == "cancelled" else "conflict" if l.id in bad else "cover" if l.id in cover else "makeup" if l.is_makeup else ""
        l.conflict_kind = bad.get(l.id)
        key = (t.strftime("%H:%M"), t.date())
        cells[key].append(l); times.add(key[0])
    # the grid rows are lesson start times, like in the design
    grid = [{"time": tm, "cols": [cells.get((tm, dd), []) for dd in days]} for tm in sorted(times)]
    sel = None
    if request.GET.get("lesson"):
        sel = next((l for l in lessons if str(l.id) == request.GET["lesson"]), None)
    panel = None
    if sel:
        studs = list(sel.group.students.filter(active=True))
        saved = {a.student_id: a.status for a in sel.attendance.all()}
        pre = {p.student_id: p for p in sel.pre_absences.all()}
        for s in studs:
            s.pre, s.current = pre.get(s.id), saved.get(s.id, "")
        panel = {"l": sel, "studs": studs, "editable": r == "admin", "future": sel.start > timezone.now(),
                 "not_marked": sum(1 for s in studs if not s.current)}
    return render(request, "schedule.html", {"days": days, "grid": grid, "mon": mon, "prev": mon - timedelta(days=7), "next": mon + timedelta(days=7),
                  "teachers": User.objects.filter(groups__name="teacher"), "rooms": Room.objects.all(), "tid": tid, "rid": rid, "panel": panel,
                  "n": len(lessons), "cover_list": [l for l in lessons if l.id in cover][:3],
                  "conflict_list": [l for l in lessons if l.id in bad][:2], "today": timezone.localdate(), "can_plan": r == "admin"})


def _recipients(lesson):
    users = {}
    for s in lesson.group.students.filter(active=True).select_related("parent", "user"):
        for u in (s.parent, s.user):
            if u:
                users[u.id] = u
    return users.values()


@role_required("admin")
def teacher_absence(request):
    """UC-4: register teacher absence -> affected lessons -> substitute or cancel (clash checks) -> notify parents."""
    today = timezone.localdate()
    teachers = User.objects.filter(groups__name="teacher").order_by("first_name", "username")
    tid = request.GET.get("teacher") or request.POST.get("teacher")
    d1 = parse_date(request.GET.get("from") or request.POST.get("from") or "") or today
    d2 = parse_date(request.GET.get("to") or request.POST.get("to") or "") or d1
    back = f"{request.path}?teacher={tid}&from={d1}&to={d2}"
    if request.method == "POST":
        P = request.POST
        if P.get("mode") == "register" and tid:
            TeacherAbsence.objects.get_or_create(teacher_id=tid, start_date=d1, end_date=d2, defaults={"reason": P.get("reason", "")[:120], "created_by": request.user})
            messages.success(request, "Teacher absence registered")
            return redirect(back)
        l = get_object_or_404(Lesson.objects.select_related("group"), pk=P.get("lesson"), status="scheduled")
        if P.get("mode") == "cancel":
            l.status, l.cancel_reason = "cancelled", P.get("reason", "")[:200]
            l.save()
            for u in _recipients(l):
                notify(u, "Lesson cancelled: {group}, {when}", group=l.group.name, when=when(l.start))
            messages.success(request, "Lesson cancelled, parents notified")
        elif P.get("mode") == "substitute":
            sub = get_object_or_404(User, pk=P.get("substitute"), groups__name="teacher")
            room = Room.objects.filter(pk=P.get("room") or 0).first() or l.room
            busy, rc = teacher_clash(sub, l.start, l.end, l.pk), room_clash(room, l.start, l.end, l.pk)
            if sub == l.group.teacher:
                messages.error(request, "Choose another teacher")
            elif busy:
                messages.error(request, f"{sub.first_name or sub.username} is busy: {busy[0]}")
            elif rc:
                messages.error(request, f"Room {room} is busy: {rc[0]} - choose another room")
            else:
                l.substitute, l.room = sub, room
                l.save()
                notify(sub, "You substitute for {group}, {when}", group=l.group.name, when=when(l.start))
                for u in _recipients(l):
                    notify(u, "Teacher change: {group}, {when}, new teacher {teacher}", group=l.group.name, when=when(l.start), teacher=sub.first_name or sub.username)
                messages.success(request, "Substitute assigned, parents notified")
        return redirect(back)
    lessons = []
    if tid:
        lessons = Lesson.objects.filter(group__teacher_id=tid, start__date__gte=d1, start__date__lte=d2).select_related("group", "room", "substitute")
    return render(request, "teacher_absence.html", {"teachers": teachers, "tid": int(tid) if tid else None, "d1": d1, "d2": d2,
                  "lessons": lessons, "rooms": Room.objects.all(), "absences": TeacherAbsence.objects.filter(end_date__gte=today).select_related("teacher")})


# ================================================================ UC-2 / FR-02 attendance
def save_record(lesson, topic, homework, due, statuses, files, saved_at):
    valid, dropped = {"present", "late", "absent"}, 0
    with transaction.atomic():
        lesson.topic, lesson.homework = topic.strip()[:200], homework.strip()
        lesson.homework_due = due
        lesson.attendance_saved_at = min(saved_at, timezone.now())
        lesson.save()
        room = 3 - lesson.files.count()                  # FR-02: up to 3 attachments
        for f in files:
            if room > 0:
                HomeworkFile.objects.create(lesson=lesson, file=f); room -= 1
            else:
                dropped += 1
        for st in lesson.group.students.filter(active=True):
            v = statuses.get(str(st.id))
            Attendance.objects.update_or_create(lesson=lesson, student=st, defaults={"status": v if v in valid else "absent"})
    return dropped


@role_required("teacher", "admin")
def lesson_attendance(request, pk):
    """Server-rendered form: used by the administrator (corrections, 'Save & notify parents') and as a fallback."""
    lesson = get_object_or_404(Lesson.objects.select_related("group"), pk=pk)
    r = role(request.user)
    if r == "teacher" and lesson.teacher != request.user:
        raise PermissionDenied
    editable = lesson.status == "scheduled" and (r == "admin" or (r == "teacher" and lesson.form_open))
    students = list(lesson.group.students.filter(active=True))
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if request.method == "POST":
        if not editable:
            return HttpResponse(status=403)
        P = request.POST
        st = {str(s.id): P.get(f"status_{s.id}") for s in students}
        dropped = save_record(lesson, P.get("topic", ""), P.get("homework", ""), parse_date(P.get("homework_due", "")), st,
                              request.FILES.getlist("homework_file"), timezone.now())
        if P.get("notify"):
            names = dict(Attendance.STATUS)
            for s in students:
                if st.get(str(s.id)) in ("late", "absent"):
                    notify(s.parent, "{student} was marked {status} at {group}, {when}", student=s.name,
                           status=names[st[str(s.id)]], group=lesson.group.name, when=when(lesson.start))
        messages.success(request, "Saved" + (" (max 3 attachments)" if dropped else ""))
        return redirect(nxt if nxt.startswith("/") else "lesson", **({} if nxt.startswith("/") else {"pk": pk}))
    saved = {a.student_id: a.status for a in lesson.attendance.all()}
    pre = {p.student_id: p for p in lesson.pre_absences.all()}
    for s in students:
        s.pre = pre.get(s.id)
        s.current = saved.get(s.id) or (s.pre.kind if s.pre else "present")
    return render(request, "lesson.html", {"lesson": lesson, "students": students, "locked": not editable, "files": lesson.files.all()})


@role_required("teacher")
def attendance_app(request):
    return render(request, "attendance_app.html", {"open_id": request.GET.get("lesson", "")})


def _teacher_lessons(user):
    return Lesson.objects.filter(Q(substitute=user) | Q(substitute__isnull=True, group__teacher=user))


@role_required("teacher")
def api_roster(request):
    now = timezone.now()
    ls = (_teacher_lessons(request.user).filter(status="scheduled", start__gte=now - timedelta(days=2), start__lte=now + timedelta(days=7))
          .select_related("group", "room").prefetch_related("attendance", "pre_absences", "files", "group__students"))
    data = []
    for l in ls:
        att = {a.student_id: a.status for a in l.attendance.all()}
        pre = {p.student_id: p for p in l.pre_absences.all()}
        data.append({"id": l.id, "group": l.group.name, "room": l.room.name if l.room else "", "start": l.start.isoformat(),
                     "end": l.end.isoformat(), "opens_at": l.opens_at.isoformat(), "closes_at": l.closes_at.isoformat(),
                     "topic": l.topic, "homework": l.homework, "due": l.homework_due.isoformat() if l.homework_due else "",
                     "files": [f.file.url for f in l.files.all()],
                     "saved_at": l.attendance_saved_at.isoformat() if l.attendance_saved_at else None,
                     "students": [{"id": s.id, "name": s.name, "status": att.get(s.id),
                                   "pre": {"kind": pre[s.id].kind, "minutes": pre[s.id].minutes, "reason": pre[s.id].reason, "note": pre[s.id].note} if s.id in pre else None}
                                  for s in l.group.students.all() if s.active]})
    return JsonResponse({"server_time": now.isoformat(), "lessons": data})


@role_required("teacher")
@require_POST
def api_push(request):
    P, uid = request.POST, request.POST.get("uuid", "")
    try:
        lesson = _teacher_lessons(request.user).select_related("group").get(pk=int(P.get("lesson", 0)))
    except (Lesson.DoesNotExist, ValueError):
        return JsonResponse({"status": "rejected", "reason": "lesson"})
    if not uid:
        return JsonResponse({"status": "rejected", "reason": "uuid"})
    if SyncLog.objects.filter(uuid=uid).exists():
        return JsonResponse({"status": "ok", "duplicate": True})
    saved_at = parse_datetime(P.get("saved_at", "")) or timezone.now()

    def final(status, **kw):
        SyncLog.objects.create(uuid=uid, user=request.user, lesson=lesson, outcome=kw.get("reason", status))
        return JsonResponse({"status": status, **kw})
    if lesson.status == "cancelled":
        return final("rejected", reason="cancelled")
    if saved_at < lesson.opens_at:
        return final("rejected", reason="too_early")
    if saved_at > lesson.closes_at:                           # read-only after 23:59 of the lesson day
        return final("rejected", reason="closed")
    if lesson.attendance_saved_at and lesson.attendance_saved_at > saved_at:
        return final("conflict")
    try:
        statuses = json.loads(P.get("statuses", "{}"))
    except ValueError:
        statuses = {}
    save_record(lesson, P.get("topic", ""), P.get("homework", ""), parse_date(P.get("due", "")), statuses,
                request.FILES.getlist("homework_file"), saved_at)
    SyncLog.objects.create(uuid=uid, user=request.user, lesson=lesson)
    return JsonResponse({"status": "ok"})


@role_required("admin")
def missing(request):
    items = missing_qs().select_related("group__teacher", "substitute", "room").order_by("-start")[:200]
    return render(request, "missing.html", {"items": items})


# ================================================================ FR-05 / UC-5 personal account + FR-03 absence
@role_required("parent", "student")
def records(request):
    u, now, r = request.user, timezone.now(), role(request.user)
    studs = list((Student.objects.filter(parent=u) if r == "parent" else Student.objects.filter(user=u)).select_related("group__course", "group__teacher"))
    child = next((s for s in studs if str(s.id) == request.GET.get("child")), studs[0] if studs else None)
    q = request.GET.get("q", "").strip().lower()
    ctx = {"studs": studs, "child": child, "q": request.GET.get("q", "")}
    if child:
        att = {a.lesson_id: a.status for a in Attendance.objects.filter(student=child)}
        pre = {p.lesson_id: p for p in PreAbsence.objects.filter(student=child)}
        lessons = list(child.group.lessons.select_related("room", "substitute").prefetch_related("files").order_by("-start")[:80])
        for l in lessons:
            l.att, l.pre = att.get(l.id), pre.get(l.id)
            l.published = l.attendance_saved_at is not None
            l.future = l.start > now
        mats = [l for l in lessons if l.published and (l.topic or l.homework or l.files.all())]
        if q:
            mats = [l for l in mats if q in (l.topic + " " + l.homework).lower()]
        fees, credit = finance.ledger(child)
        past = [l for l in lessons if not l.future and l.status == "scheduled"]
        done = [l for l in past if l.att]
        ctx.update(upcoming=sorted([l for l in lessons if l.future], key=lambda l: l.start)[:8], past=past[:15],
                   mats=mats[:12], fees=list(reversed(fees)), due=sum(f.due for f in fees), credit=credit,
                   payments=child.payments.order_by("-created_at")[:8],
                   att_pct=round(100 * sum(1 for l in done if l.att != "absent") / len(done)) if done else None,
                   can_report=r == "parent")
    return render(request, "records.html", ctx)


def _absence_student(request, student):
    s = get_object_or_404(Student.objects.select_related("group"), pk=student)
    r = role(request.user)
    if r == "parent" and s.parent_id != request.user.id or r not in ("parent", "admin"):
        raise PermissionDenied
    return s


@role_required("parent", "admin")
def absence_choose(request, student):
    """FR-03 step 1: choose a lesson (next 14 days)."""
    s = _absence_student(request, student)
    now = timezone.now()
    ls = s.group.lessons.filter(status="scheduled", start__gt=now, start__lte=now + timedelta(days=settings.ABSENCE_MAX_DAYS_AHEAD)).select_related("room")
    pre = {p.lesson_id: p for p in PreAbsence.objects.filter(student=s)}
    for l in ls:
        l.pre = pre.get(l.id)
    started = s.group.lessons.filter(start__lte=now, start__gte=now - timedelta(hours=3)).first()
    return render(request, "absence_choose.html", {"s": s, "lessons": ls, "started": started})


@role_required("parent", "admin")
def absence_form(request, student, lesson):
    """FR-03 steps 2-3: Late (5/10/15/30/60) or Absent + reason, optional period up to 14 days; refused after the lesson starts."""
    s = _absence_student(request, student)
    l = get_object_or_404(Lesson.objects.select_related("group", "room"), pk=lesson, group=s.group, status="scheduled")
    now, P = timezone.now(), request.POST
    if l.start <= now:
        return render(request, "absence_form.html", {"s": s, "l": l, "refused": True}, status=409)
    ctx = {"s": s, "l": l, "minutes": PreAbsence.LATE_MINUTES, "reasons": PreAbsence.REASONS, "pre": PreAbsence.objects.filter(lesson=l, student=s).first()}
    if request.method == "POST":
        if P.get("withdraw"):
            PreAbsence.objects.filter(lesson=l, student=s).delete()
            return render(request, "absence_done.html", {"s": s, "l": l, "withdrawn": True})
        kind, reason, note = P.get("kind"), P.get("reason", ""), P.get("note", "").strip()[:200]
        try:
            minutes = int(P.get("minutes") or 0)
        except ValueError:
            minutes = 0
        end = parse_date(P.get("until", "")) or timezone.localtime(l.start).date()
        err = None
        if kind == "late" and minutes in PreAbsence.LATE_MINUTES:
            reason, note = "", ""
        elif kind == "absent" and reason in dict(PreAbsence.REASONS) and (reason != "other" or note):
            minutes = None
        else:
            err = "Choose Late with minutes, or Absent with a reason (describe it if 'Other')"
        first_day = timezone.localtime(l.start).date()
        if not err and (end < first_day or (end - first_day).days > settings.ABSENCE_MAX_DAYS_AHEAD):
            err = "The period can be up to 14 days"
        if err:
            ctx["error"] = err
            return render(request, "absence_form.html", ctx)
        covered = list(s.group.lessons.filter(status="scheduled", start__gte=l.start, start__date__lte=end))
        covered = [x for x in covered if x.start > now] if kind == "absent" else [l]
        for x in covered:
            PreAbsence.objects.update_or_create(lesson=x, student=s, defaults={"kind": kind, "minutes": minutes or None, "reason": reason, "note": note, "set_by": request.user})
            if x.teacher:
                notify(x.teacher, "Absence notice: {student}, {group}, {when}", student=s.name, group=x.group.name, when=when(x.start))
        return render(request, "absence_done.html", {"s": s, "l": l, "covered": covered, "kind": kind, "minutes": minutes})
    return render(request, "absence_form.html", ctx)


# ================================================================ reports
@role_required("admin", "accountant")
def reports(request):
    c = {"trend": attendance_trend(), "money": collections(), "missing": missing_qs().count()}
    if role(request.user) in STAFF:
        c["funnel"] = [(lbl, Applicant.objects.filter(status=k).count()) for k, lbl in Applicant.STATUS]
        c["lost"] = [(lbl, Applicant.objects.filter(status="lost", lost_reason=k).count()) for k, lbl in LOST_REASONS]
        c["by_course"] = Student.objects.filter(active=True).values("group__course__name").annotate(n=Count("id")).order_by("-n")
    return render(request, "reports.html", c)
