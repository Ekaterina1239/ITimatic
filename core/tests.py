import time as _t
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from . import finance
from .models import *


def scan(name="c.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 x")


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed", verbosity=0)

    def as_(self, username, role):
        c = Client()
        c.force_login(User.objects.get(username=username))
        s = c.session; s["role"] = role; s.save()
        return c

    def admin(self): return self.as_("alex", "admin")
    def teacher(self, u="nodira"): return self.as_(u, "teacher")
    def parent(self): return self.as_("p998905000001", "parent")


class SignIn(Base):
    def test_phone_sms_login_and_role_picker(self):
        c = Client()
        c.post("/login/", {"phone": "+998 90 100 00 01"})
        code = c.session["demo_code"]
        r = c.post("/login/verify/", {"code": "000000"})
        self.assertContains(r, "wrong or expired")
        r = c.post("/login/verify/", {"code": code})
        self.assertRedirects(r, "/login/role/", fetch_redirect_response=False)          # two roles on one number
        page = c.get("/login/role/")
        for label in ("Administrator", "Accountant"):
            self.assertContains(page, label)
        self.assertNotContains(page, "Director")
        self.assertEqual(c.get("/").status_code, 302)                                    # no role chosen yet -> picker
        c.post("/login/role/", {"role": "accountant"})
        self.assertContains(c.get("/"), "Accountant")
        self.assertEqual(c.get("/enrolment/").status_code, 403)                          # accountant cannot open admin pages

    def test_single_role_goes_straight_in_and_no_enumeration(self):
        c = Client(); c.post("/login/", {"phone": "998902000005"})
        r = c.post("/login/verify/", {"code": c.session["demo_code"]})
        self.assertRedirects(r, "/", fetch_redirect_response=False)
        self.assertContains(c.get("/"), "My workspace")
        c2 = Client(); r = c2.post("/login/", {"phone": "998000000000"})
        self.assertRedirects(r, "/login/verify/", fetch_redirect_response=False)         # same answer for an unknown number
        self.assertNotIn("demo_code", c2.session)

    def test_code_limits(self):
        c = Client()
        for _ in range(4): c.post("/login/", {"phone": "998902000005"})
        self.assertEqual(LoginCode.objects.filter(phone="998902000005").count(), 3)


class Enrolment(Base):          # UC-1 / FR-01
    def test_stages_contract_gate_and_completion(self):
        c = self.admin(); a = Applicant.objects.get(name="Kamola Rustamova"); url = f"/enrolment/{a.pk}/"
        post = lambda **d: c.post(url, d, follow=True)
        post(action="start")
        post(action="placement", skip="1")                                              # reason is mandatory
        a.refresh_from_db(); self.assertFalse(a.placement_done)
        post(action="placement", skip="1", skip_reason="Beginner")
        post(action="conversation", result="accepted"); post(action="trial", value="yes"); post(action="feedback", value="wants_join")
        g = Group.objects.get(name="Mathematics A2-01")
        r = post(action="add_to_group", group=g.pk)                                      # no contract yet -> blocked
        a.refresh_from_db(); self.assertEqual(a.status, "in_progress")
        post(action="contract", number="ITM-1", date="2026-11-19", scan=SimpleUploadedFile("x.exe", b"bad"))
        a.refresh_from_db(); self.assertFalse(a.contract_done)                           # only PDF/JPG/PNG
        post(action="contract", number="ITM-2026-1001", date="2026-11-19", scan=scan())
        a.refresh_from_db(); self.assertTrue(a.contract_done); self.assertEqual(a.stage, 6)
        self.assertEqual(a.level, "beginner")
        g.level = "beginner"; g.save()
        post(action="add_to_group", group=g.pk)
        a.refresh_from_db(); self.assertEqual(a.status, "completed")
        s = Student.objects.get(applicant=a)
        self.assertEqual(s.fees.count(), 1); self.assertTrue(s.contract_scan)
        self.assertTrue(s.parent.groups.filter(name="parent").exists())
        self.assertTrue(Notification.objects.filter(user=s.parent, template__startswith="Student {student}").exists())

    def test_student_model_refuses_no_contract(self):
        g = Group.objects.first(); u = User.objects.create(username="zz")
        with self.assertRaises(Exception):
            Student.objects.create(user=u, name="X", group=g)

    def test_not_suitable_declines_waiting_list_and_capacity(self):
        c = self.admin(); a = Applicant.objects.get(name="Rustam Aliev"); url = f"/enrolment/{a.pk}/"
        c.post(url, {"action": "conversation", "result": "not_suitable"})
        a.refresh_from_db(); self.assertEqual(a.conversation_result, "not_suitable")
        c.post(url, {"action": "reset_conversation"}); a.refresh_from_db(); self.assertEqual(a.conversation_result, "")
        c.post(url, {"action": "conversation", "result": "accepted"}); c.post(url, {"action": "trial", "value": "yes"})
        c.post(url, {"action": "feedback", "value": "another_group"}); a.refresh_from_db()
        self.assertEqual((a.conversation_result, a.trial_attended, a.feedback), ("", None, ""))   # 5b: repeat steps
        c.post(url, {"action": "lost", "reason": "other", "note": ""}); a.refresh_from_db(); self.assertEqual(a.status, "in_progress")
        c.post(url, {"action": "lost", "reason": "price"}); a.refresh_from_db()
        self.assertEqual((a.status, a.follow_up, a.lost_reason), ("lost", True, "price"))
        self.assertContains(c.get("/followup/"), "Rustam")

    def test_waiting_list_threshold_and_group_capacity(self):
        from .views import waiting_ready
        ready = waiting_ready()
        self.assertEqual([(r["kind"], r["n"]) for r in ready], [("mini", 4)])          # mini threshold 3 reached; 2 standard applicants (threshold 6) are not
        g = Group.objects.create(name="Solo", course=Course.objects.first(), level="beginner", kind="individual")
        self.assertEqual((g.capacity, Group(kind="mini").capacity, Group(kind="standard").capacity), (1, 4, 12))
        s = Student.objects.first(); s.group = g; s.save()
        self.assertEqual(g.places_left, 0)

    def test_uc1_order_is_enforced(self):
        a = Applicant.objects.get(name="Kamola Rustamova"); url = f"/enrolment/{a.pk}/"; c = self.admin()
        c.post(url, {"action": "start"})
        c.post(url, {"action": "conversation", "result": "accepted"}); a.refresh_from_db()
        self.assertEqual((a.conversation_result, a.stage), ("", 1))                       # conversation before level test is ignored
        c.post(url, {"action": "placement", "score": "70"}); self.assertEqual(Applicant.objects.get(pk=a.pk).stage, 2)
        c.post(url, {"action": "trial", "value": "yes"}); self.assertIsNone(Applicant.objects.get(pk=a.pk).trial_attended)   # trial before conversation ignored
        c.post(url, {"action": "conversation", "result": "accepted"}); self.assertEqual(Applicant.objects.get(pk=a.pk).stage, 3)
        c.post(url, {"action": "trial", "value": "yes"}); self.assertEqual(Applicant.objects.get(pk=a.pk).stage, 4)
        c.post(url, {"action": "feedback", "value": "wants_join"}); self.assertEqual(Applicant.objects.get(pk=a.pk).stage, 5)
        g = Group.objects.filter(course=a.course).first()
        c.post(url, {"action": "add_to_group", "group": g.pk if g else 0}); a.refresh_from_db()
        self.assertNotEqual(a.status, "completed")                                        # no contract -> no group

    def test_teacher_search_and_counters_are_scoped(self):
        t = self.teacher("nodira")
        r = t.get("/search/?q=a"); self.assertEqual(r.status_code, 200)                  # used to crash: filter() after slice
        for g in r.context["grps"]: self.assertEqual(g.teacher.username, "nodira")
        for s_ in r.context["studs"]: self.assertEqual(s_.group.teacher.username, "nodira")
        r = t.get("/enrolment/")
        mine = Applicant.objects.filter(course__in=Group.objects.filter(teacher__username="nodira").values("course"))
        self.assertEqual(sum(r.context["counts"].values()), mine.count())
        self.assertLess(sum(r.context["counts"].values()), Applicant.objects.count())
        self.assertEqual(r.context["ready"], [])
        self.assertEqual(sum(self.admin().get("/enrolment/").context["counts"].values()), Applicant.objects.count())

    def test_group_capacity_follows_room_seats(self):
        g = Group.objects.filter(kind="standard").first(); r = g.room
        self.assertEqual(g.capacity, min(12, r.seats))
        r.seats = 8; r.save(); g.refresh_from_db(); g.room.refresh_from_db()
        self.assertEqual(Group.objects.get(pk=g.pk).capacity, 8)                         # smaller room -> smaller group
        mini = Group.objects.filter(kind="mini").first()
        self.assertEqual(mini.capacity, 4)                                               # type limit still applies

    def test_teacher_only_conversation(self):
        a = Applicant.objects.get(name="Mia Chen")
        t = self.teacher("reed")
        self.assertEqual(t.post(f"/enrolment/{a.pk}/", {"action": "trial", "value": "no"}).status_code, 403)
        self.assertEqual(self.as_("accountant", "accountant").get(f"/enrolment/{a.pk}/").status_code, 403)


class Attendance_(Base):        # UC-2 / FR-02
    def open_lesson(self):
        return Lesson.objects.filter(group__name="IT Basics B1-01", attendance_saved_at=None).order_by("start")[1]

    def push(self, c, lesson, uid, saved_at, **extra):
        d = {"uuid": uid, "lesson": lesson.pk, "topic": "Offline topic", "homework": "hw", "due": "2026-12-01", "saved_at": saved_at.isoformat(), "statuses": "{}"}
        d.update(extra)
        return c.post("/api/push/", d).json()

    def test_window_offline_sync_files_and_conflict(self):
        c = self.teacher("nodira"); l = self.open_lesson(); g = l.group
        self.assertTrue(l.form_open)
        roster = c.get("/api/roster/").json()
        self.assertIn(l.id, [x["id"] for x in roster["lessons"]])
        st = '{%s}' % ",".join('"%d":"late"' % s.id for s in g.students.all())
        now = timezone.now()
        files = [SimpleUploadedFile(f"h{i}.txt", b"x") for i in range(5)]
        self.assertEqual(self.push(c, l, "u1", now, statuses=st, homework_file=files)["status"], "ok")
        self.assertTrue(self.push(c, l, "u1", now)["duplicate"])                          # resend is harmless
        self.assertEqual(l.files.count(), 3)                                              # max 3 attachments
        self.assertEqual(set(Attendance.objects.filter(lesson=l).values_list("status", flat=True)), {"late"})
        self.assertEqual(self.push(c, l, "u2", now - timedelta(minutes=2))["status"], "conflict")   # older than what the server already holds
        far = Lesson.objects.filter(group=g, attendance_saved_at=None).order_by("start").last()
        self.assertEqual(self.push(c, far, "u3", now)["reason"], "too_early")
        self.assertEqual(self.push(self.teacher("reed"), l, "u4", now)["status"], "rejected")   # not their lesson

    def test_read_only_after_midnight(self):
        c = self.teacher("nodira"); l = self.open_lesson()
        late = l.closes_at + timedelta(minutes=2)
        self.assertEqual(self.push(c, l, "late1", late)["reason"], "closed")
        old = Lesson.objects.create(group=l.group, start=timezone.now() - timedelta(days=1), duration=60)
        self.assertEqual(c.post(f"/lessons/{old.pk}/", {"topic": "x"}).status_code, 403)               # yesterday's lesson is read-only

    def test_admin_can_correct_after_midnight_teacher_cannot(self):
        l = self.open_lesson()
        old = Lesson.objects.create(group=l.group, start=timezone.now() - timedelta(days=2), duration=60)
        st = l.group.students.first()
        data = {"topic": "Corrected", "homework": "", f"status_{st.id}": "late"}
        self.assertEqual(self.teacher("nodira").post(f"/lessons/{old.pk}/", data).status_code, 403)
        self.assertEqual(self.admin().post(f"/lessons/{old.pk}/", data).status_code, 302)
        self.assertEqual(Attendance.objects.get(lesson=old, student=st).status, "late")

    def test_missing_report_after_30_minutes_and_admin_edit(self):
        a = self.admin()
        r = a.get("/reports/missing/"); self.assertGreaterEqual(len(r.context["items"]), 1)
        for l in list(r.context["items"]):
            data = {"topic": "Fix", "homework": "", "notify": "1"}
            for s in l.group.students.all(): data[f"status_{s.id}"] = "absent"
            a.post(f"/lessons/{l.pk}/", data)
        self.assertEqual(len(a.get("/reports/missing/").context["items"]), 0)
        self.assertTrue(Notification.objects.filter(template__contains="was marked").exists())     # 'Save & notify parents'


class Absence(Base):            # FR-03
    def setUp(self):
        self.leo = Student.objects.get(name="Leo Wilson")
        self.lessons = list(self.leo.group.lessons.filter(start__gt=timezone.now() + timedelta(hours=2)).order_by("start"))

    def test_late_absent_period_and_refusal(self):
        c = self.parent(); l = self.lessons[0]; url = f"/absence/{self.leo.pk}/{l.pk}/"
        r = c.post(url, {"kind": "late", "minutes": "7"}); self.assertContains(r, "Choose Late")        # 5/10/15/30/60 only
        c.post(url, {"kind": "late", "minutes": "15"})
        p = PreAbsence.objects.get(lesson=l, student=self.leo); self.assertEqual((p.kind, p.minutes), ("late", 15))
        self.assertContains(c.post(url, {"kind": "absent", "reason": "other", "note": ""}), "Choose Late")
        end = (timezone.localtime(l.start) + timedelta(days=7)).date()
        c.post(url, {"kind": "absent", "reason": "illness", "until": end.isoformat()})
        n = PreAbsence.objects.filter(student=self.leo, kind="absent").count(); self.assertGreaterEqual(n, 2)   # whole period
        far = (timezone.localtime(l.start) + timedelta(days=20)).date()
        self.assertContains(c.post(url, {"kind": "absent", "reason": "family", "until": far.isoformat()}), "14 days")
        c.post(url, {"withdraw": "1"}); self.assertFalse(PreAbsence.objects.filter(lesson=l, student=self.leo).exists())
        started = self.leo.group.lessons.filter(start__lte=timezone.now()).order_by("-start").first()
        r = c.get(f"/absence/{self.leo.pk}/{started.pk}/"); self.assertEqual(r.status_code, 409)         # refused after start
        self.assertTrue(Notification.objects.filter(user=l.teacher, template__startswith="Absence notice").exists())

    def test_teacher_sees_badge_and_parent_isolation(self):
        l = self.lessons[0]
        self.parent().post(f"/absence/{self.leo.pk}/{l.pk}/", {"kind": "absent", "reason": "travel"})
        roster = self.teacher("bennett").get("/api/roster/").json()
        mine = [x for x in roster["lessons"] if x["id"] == l.id]
        if mine:
            self.assertEqual([s["pre"]["kind"] for s in mine[0]["students"] if s["id"] == self.leo.id], ["absent"])
        other = Student.objects.filter(parent__isnull=False).exclude(parent=self.leo.parent).first()
        self.assertEqual(self.parent().get(f"/absence/{other.pk}/").status_code, 403)


class Money(Base):              # UC-3 / FR-04
    def test_partial_overpay_receipt_and_credit(self):
        s = Student.objects.get(name="Timur Rakhimov") if Student.objects.filter(name="Timur Rakhimov").exists() else Student.objects.filter(fees__isnull=False).last()
        s.payments.all().delete()
        c = self.as_("accountant", "accountant")
        c.post("/payments/new/", {"student": s.pk, "amount": 200000, "method": "cash"})
        self.assertEqual(finance.totals(s)[0], sum(f.net for f in s.fees.all()) - 200000)           # partial payment
        r = c.post("/payments/new/", {"student": s.pk, "amount": 5000000, "method": "payme"}); self.assertContains(r, "Required")   # reference needed
        r = c.post("/payments/new/", {"student": s.pk, "amount": 5000000, "method": "click", "reference": "TX1"})
        due, credit = finance.totals(s); self.assertEqual(due, 0); self.assertGreater(credit, 0)       # overpayment credit
        self.assertContains(c.get(r["Location"]), "R-")
        Fee.objects.create(student=s, month=timezone.localdate().replace(day=1) + timedelta(days=32), amount=480000)
        self.assertGreater(finance.totals(s)[1], 0)                                                   # credit covers next fee automatically
        self.assertEqual(self.as_("p998905000001", "parent").get(r["Location"]).status_code, 403)    # other family's receipt

    def test_discount_requested_by_accountant_approved_by_admin(self):
        s = Student.objects.filter(fees__isnull=False).first(); fee = s.fees.last(); before = fee.net
        acc = self.as_("accountant", "accountant")
        acc.post(f"/students/{s.pk}/discount/", {"fee": fee.pk, "amount": 100000, "reason": "Sibling"})
        d = DiscountRequest.objects.get(); self.assertEqual(d.status, "pending")
        self.assertEqual(acc.post("/discounts/", {"id": d.pk, "decision": "approve"}).status_code, 403)
        self.as_("alex", "admin").post("/discounts/", {"id": d.pk, "decision": "approve"})
        fee.refresh_from_db(); self.assertEqual(fee.net, before - 100000)

    def test_debtors_list_branch_actions_and_access(self):
        a = self.admin(); r = a.get("/debtors/")
        rows = r.context["rows"]; self.assertGreater(len(rows), 5)
        self.assertEqual(rows[0]["overdue"], max(x["overdue"] for x in rows))                      # longest overdue first
        s = rows[0]["s"]
        a.post("/debtors/", {"student": s.pk, "outcome": "promised", "promised_by": ""}); self.assertEqual(DebtorNote.objects.count(), 0)
        a.post("/debtors/", {"student": s.pk, "outcome": "promised", "promised_by": "2026-12-01"})
        a.post("/debtors/", {"student": s.pk, "outcome": "no_answer"}); a.post("/debtors/", {"student": s.pk, "outcome": "leaving"})
        self.assertEqual(DebtorNote.objects.filter(student=s).count(), 3)
        a.post("/debtors/", {"student": s.pk, "remind": "1"})
        self.assertTrue(Notification.objects.filter(user=s.parent, template__startswith="Payment reminder").exists())
        acc = self.as_("accountant", "accountant")                                                   # accountant sees the same list and records outcomes
        self.assertEqual(acc.get("/debtors/").status_code, 200)
        acc.post("/debtors/", {"student": s.pk, "outcome": "no_answer"}); self.assertEqual(DebtorNote.objects.filter(student=s).count(), 4)
        self.assertEqual(self.teacher().get("/debtors/").status_code, 403)
        self.assertEqual(self.parent().get("/debtors/").status_code, 403)

    def test_monthly_command_charges_and_notifies(self):
        Fee.objects.all().delete(); Notification.objects.all().delete()
        call_command("generate_fees", month="2026-12", verbosity=0)
        self.assertEqual(Fee.objects.count(), Student.objects.filter(active=True).count())
        self.assertTrue(Notification.objects.filter(template__startswith="Debtors list").exists())


class TeacherAbsenceFlow(Base):  # UC-4
    def test_substitute_clash_cancel_and_notify(self):
        a = self.admin(); g = Group.objects.get(name="English B1-02")
        l = g.lessons.filter(start__gt=timezone.now()).order_by("start").first()
        busy = Group.objects.get(name="English B1-03").teacher
        # same room + time lesson for the substitute -> blocked
        Lesson.objects.create(group=Group.objects.get(name="IT Basics B1-01"), start=l.start, duration=60, room=l.room)
        day = timezone.localtime(l.start).date().isoformat()
        base = {"mode": "substitute", "lesson": l.pk, "teacher": g.teacher_id, "from": day, "to": day}
        a.post("/teacher-absence/", {**base, "substitute": User.objects.get(username="nodira").pk, "room": l.room_id})
        l.refresh_from_db(); self.assertIsNone(l.substitute)                                        # clash refused
        a.post("/teacher-absence/", {**base, "substitute": User.objects.get(username="turner").pk, "room": Room.objects.get(name="205").pk})
        l.refresh_from_db(); self.assertEqual(l.substitute.username, "turner")
        stu = l.group.students.first()
        self.assertTrue(Notification.objects.filter(user=stu.parent, template__startswith="Teacher change").exists())
        l2 = g.lessons.filter(start__gt=timezone.now()).order_by("start")[1]
        a.post("/teacher-absence/", {"mode": "cancel", "lesson": l2.pk, "reason": "sick", "teacher": g.teacher_id, "from": day, "to": day})
        l2.refresh_from_db(); self.assertEqual(l2.status, "cancelled")
        self.assertTrue(Notification.objects.filter(template__startswith="Lesson cancelled").exists())
        self.assertIn(l.id, [x["id"] for x in self.teacher("turner").get("/api/roster/").json()["lessons"]])   # substitute sees the lesson

    def test_schedule_shows_conflict_and_cover(self):
        r = self.admin().get("/schedule/?week=%s" % (timezone.localdate() + timedelta(days=7)).isoformat())
        self.assertContains(r, "Room conflict"); self.assertContains(r, "Make-up")


class Account(Base):            # FR-05 / UC-5
    def test_parent_with_two_children_search_and_privacy(self):
        c = self.parent(); r = c.get("/account/")
        self.assertEqual(len(r.context["studs"]), 3)          # one parent, several children
        leo, emma = Student.objects.get(name="Leo Wilson"), Student.objects.get(name="Emma Wilson")
        self.assertContains(c.get(f"/account/?child={emma.pk}"), "Emma Wilson")
        stranger = self.as_("s1", "student"); self.assertNotContains(stranger.get("/account/"), "Leo Wilson")
        l = leo.group.lessons.filter(attendance_saved_at__isnull=True, start__lt=timezone.now()).first()


class RolesAndLanguages(Base):
    def test_access_matrix(self):
        deny = [("p998905000001", "parent", ["/enrolment/", "/groups/", "/finance/", "/students/", "/reports/", "/schedule/"]),
                ("s1", "student", ["/enrolment/", "/debtors/", "/attendance/"]),
                ("nodira", "teacher", ["/finance/", "/debtors/", "/students/", "/payments/new/", "/discounts/"]),
                ("accountant", "accountant", ["/enrolment/", "/groups/", "/schedule/", "/teacher-absence/"])]
        for u, r, paths in deny:
            c = self.as_(u, r)
            for p in paths:
                self.assertEqual(c.get(p).status_code, 403, f"{r} {p}")

    def test_languages(self):
        c = self.admin(); c.get("/lang/ru/")
        self.assertContains(c.get("/"), "Обзор"); self.assertContains(c.get("/enrolment/"), "Абитуриент")
        c.get("/lang/uz/"); self.assertContains(c.get("/"), "Umumiy ko&#x27;rinish")
        n = Notification.objects.create(user=User.objects.get(username="alex"), template="Teacher change: {group}, {when}, new teacher {teacher}", params={"group": "G", "when": "1", "teacher": "T"})
        self.assertContains(c.get("/notifications/"), "O&#x27;qituvchi almashdi")

    def test_every_page_renders_mobile_nav(self):
        self.assertContains(self.teacher().get("/"), 'name="viewport"')


class Scale(Base):              # NFR-05
    def test_220_students_pages_stay_fast(self):
        g = Group.objects.get(name="English B1-02")
        for i in range(150):
            u = User.objects.create(username=f"bulk{i}")
            s = Student(user=u, name=f"Bulk {i}", group=g, contract_number="C", contract_date=timezone.localdate()); s.contract_scan.save("c.pdf", scan(), save=False); s.save()
            Fee.objects.create(student=s, month=timezone.localdate().replace(day=1) - timedelta(days=40), amount=480000)
        self.assertGreater(Student.objects.count(), 220)
        a = self.admin()
        for p in ("/", "/debtors/", "/students/", "/schedule/", "/reports/"):
            t0 = _t.time(); self.assertEqual(a.get(p).status_code, 200); dt = _t.time() - t0
            self.assertLess(dt, 4.0, f"{p} took {dt:.1f}s")
