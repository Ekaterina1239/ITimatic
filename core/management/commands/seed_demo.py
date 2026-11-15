"""Demo data that mirrors the Figma design (Autumn term 2026, Chilonzor / Yunusobod)."""

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    ROLES, AbsenceReport, Applicant, Assessment, Attendance, Branch, Certificate, Charge,
    Group, Lesson, Notification, Payment, Student, User, UserRole,
)

DAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
# name, teacher key, course, level, days, start, minutes, room, ages
GROUPS = [
    ("English B1-02", "olivia", "English", "B1", ("Mon", "Wed"), "16:00", 60, "204", "12–14"),
    ("Mathematics A2-01", "sophie", "Mathematics", "A2", ("Mon", "Wed"), "14:00", 60, "101", "10–12"),
    ("English A2-01", "daniel", "English", "A2", ("Mon", "Thu"), "15:00", 60, "203", "11–13"),
    ("English B1-03", "olivia", "English", "B1", ("Tue", "Thu"), "16:00", 60, "204", "13–15"),
    ("Science B1-01", "james", "Science", "B1", ("Mon", "Tue"), "16:00", 90, "Lab 1", "12–14"),
    ("Mathematics B1-01", "sophie", "Mathematics", "B1", ("Mon", "Thu"), "17:30", 60, "101", "13–15"),
    ("English B2-01", "daniel", "English", "B2", ("Mon", "Fri"), "18:30", 60, "203", "15–17"),
    ("IELTS 6-01", "daniel", "IELTS", "6.0", ("Wed",), "16:00", 90, "205", "16+"),
]
FIRST = ["Aziz", "Malika", "Henry", "Zoe", "Mia", "Jasur", "Kamila", "Daniel", "Sardor", "Nilufar", "Timur", "Ruby",
         "Bekzod", "Grace", "Alisher", "Laylo", "Max", "Dilnoza", "Sam", "Umid", "Sevara", "Jack", "Shakhzod", "Ella",
         "Javohir", "Farida", "Otabek", "Madina", "Rustam", "Aisha", "Islom", "Lily", "Bobur", "Nigora", "Adam", "Zarina",
         "Kevin", "Mohira", "Eldor", "Hannah", "Diyor", "Shahzoda", "Felix", "Gulnoza", "Asad", "Nora", "Behruz", "Yasmin",
         "Akmal", "Iroda", "Tom", "Sabina", "Ravshan", "Emily", "Khurshid", "Lola", "Ulugbek", "Rose", "Doniyor", "Komila"]
LAST = ["Karimov", "Yusupova", "Adams", "Harris", "Turner", "Aliev", "Rashidova", "Kim", "Tursunov", "Saidova", "Abdullaev",
        "Green", "Ergashev", "Hall", "Nazarov", "Umarova", "Cooper", "Ismoilova", "Wright", "Rakhimov", "Khodjaeva", "Lewis"]
EXTRA_NAMES = ["Leo Wilson"] + [f"{FIRST[i % len(FIRST)]} {LAST[(i * 7 + i // len(FIRST)) % len(LAST)]}" for i in range(90)]
_OLD_NAMES = [
    "Aziz Karimov", "Malika Yusupova", "Henry Adams", "Zoe Harris", "Mia Turner", "Jasur Aliev", "Kamila Rashidova",
    "Leo Wilson", "Daniel Kim", "Sardor Tursunov", "Nilufar Saidova", "Timur Abdullaev", "Ruby Green", "Bekzod Ergashev",
    "Grace Hall", "Alisher Nazarov", "Laylo Umarova", "Max Turner", "Dilnoza Ismoilova", "Sam Cooper", "Umid Rakhimov",
    "Sevara Khodjaeva", "Jack Lewis", "Shakhzod Mirzaev", "Ella Wright", "Javohir Sobirov", "Farida Tashkentova",
    "Otabek Hasanov",
]


class Command(BaseCommand):
    help = "Load demo data (phones: 900001448 staff roles, 901111111 teacher, 902222222 parent, 903333333 student)"

    def handle(self, *args, **kwargs):
        if Student.objects.exists():
            self.stdout.write("Demo data already loaded.")
            return

        def user(phone, first, last, roles):
            u, _ = User.objects.get_or_create(phone=phone, defaults={"username": phone, "first_name": first, "last_name": last})
            for r in roles:
                UserRole.objects.get_or_create(user=u, role=r)
            return u

        user("900001448", "Alex", "Morgan", [r for r, _ in ROLES if r not in ("teacher", "parent", "student")])
        teachers = {
            "olivia": user("901111111", "Olivia", "Bennett", ["teacher"]),
            "daniel": user("901111112", "Daniel", "Reed", ["teacher"]),
            "nodira": user("901111113", "Nodira", "Karimova", ["teacher"]),
            "sophie": user("901111114", "Sophie", "Turner", ["teacher"]),
            "james": user("901111115", "James", "Ellis", ["teacher"]),
            "michael": user("901111116", "Michael", "Carter", ["teacher"]),
        }
        sarah = user("902222222", "Sarah", "Wilson", ["parent"])
        emma_user = user("903333333", "Emma", "Wilson", ["student"])
        ch, _ = Branch.objects.get_or_create(name="Chilonzor")
        Branch.objects.get_or_create(name="Yunusobod")

        today = timezone.localdate()
        monday = today - dt.timedelta(days=today.weekday())
        groups = {}
        for name, tkey, course, level, days, start, minutes, room, ages in GROUPS:
            h, m = map(int, start.split(":"))
            end = (dt.datetime(2000, 1, 1, h, m) + dt.timedelta(minutes=minutes)).time()
            groups[name] = Group.objects.create(
                name=name, branch=ch, teacher=teachers[tkey], course=course, level=level,
                schedule=f"{' / '.join(days)} · {start}–{end:%H:%M} · {room}", capacity=12,
            )
            groups[name].ages, groups[name].days, groups[name].times, groups[name].room = ages, days, (dt.time(h, m), end), room
        Group.objects.create(name="English A1-02", branch=ch, teacher=teachers["daniel"], course="English",
                             level="A1", status="closed", active=False, schedule="Closed 30 Oct 2026")

        # students ---------------------------------------------------------------
        main = groups["English B1-02"]
        core_names = ["Emma Wilson", "Lucas Martin", "Noah Patel", "Ava Robinson", "Ethan Brooks",
                      "Sofia Ahmed", "Oscar Lee", "Isabella Brown", "Amir Khan", "Chloe Evans"]
        phone = iter(range(905000001, 905999999))
        parent_names = ["Sarah Wilson", "Anna Martin", "Priya Patel", "Helen Robinson", "David Brooks", "Rana Ahmed",
                        "Min Lee", "Kate Brown", "Zara Khan", "Laura Evans"]

        def parent_for(full):
            first, last = full.split(" ", 1)
            return user(str(next(phone)), first, last, ["parent"])

        students = []
        for i, n in enumerate(core_names):
            p = sarah if i == 0 else parent_for(parent_names[i])
            students.append(Student.objects.create(name=n, branch=ch, group=main, parent=p, user=emma_user if i == 0 else None))
        others = [g for g in groups.values() if g is not main]
        sizes = [9, 10, 8, 9, 11, 8, 7]
        it = iter(EXTRA_NAMES)
        for g, size in zip(others, sizes):
            for _ in range(size):
                n = next(it)
                p = sarah if n == "Leo Wilson" else parent_for(FIRST[len(students) % len(FIRST)] + " " + n.split()[1])
                target = groups["Mathematics A2-01"] if n == "Leo Wilson" else g
                students.append(Student.objects.create(name=n, branch=ch, group=target, parent=p))

        # lessons ------------------------------------------------------------------
        for g in groups.values():
            for week in (0, 1):
                for d in g.days:
                    date = monday + dt.timedelta(days=DAYS[d] + 7 * week)
                    Lesson.objects.create(group=g, date=date, start=g.times[0], end=g.times[1], room=g.room)
        # make-up lesson and a cover-pending lesson as in the design
        Lesson.objects.create(group=main, date=monday + dt.timedelta(days=4), start=dt.time(17, 30), end=dt.time(18, 30), room="204")
        # double-booked room 101 on Thursday 17:30 (Resolve room conflict in the design)
        Lesson.objects.create(group=groups["Mathematics A2-01"], date=monday + dt.timedelta(days=3), start=dt.time(17, 30),
                              end=dt.time(18, 30), room="101")

        topics = {"English": ("Past tenses", "Unit 4 · Tell a story"), "Mathematics": ("Fractions", "Exercises 4.1–4.6"),
                  "Science": ("States of matter", "Lab report"), "IELTS": ("Writing task 2", "Essay: technology"),}
        for lesson in Lesson.objects.filter(date__lt=today).select_related("group"):
            topic, hw = topics.get(lesson.group.course, ("Revision", "Workbook p. 12"))
            lesson.topic, lesson.homework = topic, hw
            lesson.homework_due = lesson.date + dt.timedelta(days=2)
            lesson.completed = True
            lesson.save()
            for s in lesson.group.students.all():
                status = "unexplained" if s.name in ("Lucas Martin", "Ethan Brooks") else "present"
                if s.name == "Noah Patel":
                    status = "excused"
                stamp = timezone.make_aware(dt.datetime.combine(lesson.date, lesson.end))
                Attendance.objects.create(lesson=lesson, student=s, status=status, recorded_at=stamp, synced_at=stamp)
        # attendance history for Emma's term (gives the trend chart some shape)
        for weeks_ago, pct in ((5, 0.92), (4, 0.95), (3, 0.93), (2, 0.96)):
            d = monday - dt.timedelta(weeks=weeks_ago)
            old = Lesson.objects.create(group=main, date=d, start=dt.time(16), end=dt.time(17), room="204",
                                        topic="Unit %d" % (6 - weeks_ago), completed=True)
            for k, s in enumerate(main.students.all()):
                st = "present" if k < round(pct * 10) else "unexplained"
                Attendance.objects.create(lesson=old, student=s, status=st)

        # money --------------------------------------------------------------------
        nov = dt.date(2026, 11, 1)
        paid_methods = ["Bank transfer", "Card", "Cash"]
        for i, s in enumerate(students):
            due = dt.date(2026, 11, 1 if i % 3 != 2 else 15)
            Charge.objects.create(student=s, month=nov, amount=480000, due=due)
            Charge.objects.create(student=s, month=dt.date(2026, 10, 1), amount=480000, due=dt.date(2026, 10, 1))
            Payment.objects.create(student=s, month=dt.date(2026, 10, 1), amount=480000, method="Bank transfer",
                                   paid_on=dt.date(2026, 10, 2), receipt_no=f"ITM-2026-{900 + i}")
            paid = s.name not in ("Lucas Martin", "Ava Robinson", "Ethan Brooks", "Chloe Evans", "Aziz Karimov", "Jasur Aliev")
            if paid and due.day == 1:
                Payment.objects.create(student=s, month=nov, amount=480000, method=paid_methods[i % 3],
                                       paid_on=dt.date(2026, 11, 2), receipt_no=f"ITM-2026-{1000 + i}")

        # payment history June–September (for the "Payment collections" trend)
        for month, share in ((6, 0.55), (7, 0.65), (8, 0.72), (9, 0.86)):
            first = dt.date(2026, month, 1)
            for s in students[: round(len(students) * share)]:
                Charge.objects.create(student=s, month=first, amount=480000, due=first)
                Payment.objects.create(student=s, month=first, amount=480000, method="Bank transfer",
                                       paid_on=first + dt.timedelta(days=2), receipt_no="")

        # assessments, certificates -----------------------------------------------------
        for s, scores in ((students[0], (78, 84)), (students[1], (68, 72)), (students[2], (78, 81))):
            Assessment.objects.create(student=s, subject="English", name="Unit 2 assessment", date=today - dt.timedelta(days=34), score=scores[0])
            Assessment.objects.create(student=s, subject="English", name="Unit 3 assessment", date=today - dt.timedelta(days=9), score=scores[1])
            Assessment.objects.create(student=s, subject="English", name="Unit 4 quiz", date=today + dt.timedelta(days=5))
        leo = Student.objects.get(name="Leo Wilson")
        Assessment.objects.create(student=leo, subject="Mathematics", name="Fractions test", date=today - dt.timedelta(days=7), score=88)
        for name, sc, at in (("Emma Wilson", 84, 96), ("Lucas Martin", 87, 94), ("Noah Patel", 91, 98)):
            Certificate.objects.create(student=Student.objects.get(name=name), group=main, score=sc, attendance=at)

        # enrolment pipeline (Enrolment workspace in the design) ---------------------------
        A = Applicant.objects.create
        mia = A(name="Mia Chen", parent_name="Grace Chen", phone="+998 90 000 14 48", subject="English", level="B1", branch=ch,
                stage="Agreement", assigned=User.objects.get(phone="900001448"))
        mia.level_test.record(78, today - dt.timedelta(days=13), "B1")
        trial = mia.trial
        trial.conversation, trial.attendance, trial.feedback = "Accepted", "Attended", "Wants to join"
        trial.save()
        mia.contract.prepare()
        for n, parent, subj, lvl, stage, score in (
            ("Oliver Davis", "Helen Davis", "English", "A2", "Trial booked", 62),
            ("Isla Thompson", "Adam Thompson", "Mathematics", "B1", "Trial completed", 81),
            ("Leo Garcia", "Ana Garcia", "Mathematics", "A2", "Group matching", 67),
            ("Amelia Scott", "Ruth Scott", "English", "", "Assessment", None),
            ("Henry Adams", "Peter Adams", "English", "B1", "Confirmed", 75),
            ("Zoe Harris", "Lucy Harris", "English", "B1", "Group matching", 73),
            ("Jack Lewis", "Ben Lewis", "English", "B2", "Lost", 89),
        ):
            app = A(name=n, parent_name=parent, phone=f"+998 90 {next(phone) % 1000:03d} 11 22", subject=subj, level=lvl,
                    branch=ch, stage=stage, waiting=n == "Zoe Harris", lost_reason="Schedule" if stage == "Lost" else "")
            if score is not None:
                app.level_test.record(score, today - dt.timedelta(days=10), lvl)
            if stage in ("Trial completed", "Confirmed"):
                trial = app.trial
                trial.conversation, trial.attendance = "Accepted", "Attended"
                trial.feedback = "Wants to join" if stage == "Confirmed" else ""
                trial.save()

        # messages for the family account --------------------------------------------------
        for kind, text in (
            ("payment", "Payment reminder: November tuition was due on 1 Nov. Payment received on 2 Nov — no action needed."),
            ("schedule", "Make-up lesson: Emma’s missed lesson is now Fri 17:30–18:30 in Room 204. No extra fee."),
            ("schedule", "Teacher cover: Olivia is unwell. We are arranging a substitute for Wed and will confirm shortly."),
        ):
            Notification.objects.create(user=sarah, kind=kind, text=text)
        # Olivia's sick notice for next Wednesday (Teacher absence handling in the design)
        from core.models import LeaveRequest
        nxt_wed = monday + dt.timedelta(days=9)
        LeaveRequest.objects.create(teacher=teachers["olivia"], start=nxt_wed, end=nxt_wed, reason="Sick leave",
                                    note="Fever, doctor’s note to follow")
        self.stdout.write("Demo data loaded.")