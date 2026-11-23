import random
from datetime import timedelta, datetime, time
from django.contrib.auth.models import Group as AG, User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import *

FIRST = ["Leo", "Aziz", "Malika", "Henry", "Zoe", "Mia", "Jasur", "Kamila", "Daniel", "Emma", "Sam", "Umid", "Sevara", "Jack", "Shakhzod", "Ella",
         "Javohir", "Farida", "Lucas", "Ava", "Ethan", "Chloe", "Noah", "Sofia", "Amir", "Nilufur", "Bekzod", "Laylo", "Madina", "Islom", "Nigora", "Kevin",
         "Hannah", "Felix", "Nora", "Akmal", "Sabina", "Khurshid", "Rose", "Ruby", "Timur", "Dilnoza", "Otabek", "Zarina", "Bobur", "Gulnora", "Sardor", "Aisha"]
LAST = ["Wilson", "Karimov", "Kim", "Nazarov", "Lewis", "Rashidova", "Hall", "Khodjaeva", "Aliev", "Martin", "Robinson", "Brooks", "Evans", "Patel", "Ahmed",
        "Cooper", "Umarov", "Ergashev", "Green", "Abdullaev", "Saidov", "Tursunov", "Ismoilov", "Harris", "Turner", "Yusupov", "Rakhimov"]


class Command(BaseCommand):
    help = "Create demo data (8 groups, ~72 students, this week's schedule)"

    def add_arguments(self, p):
        p.add_argument("--students", type=int, default=72)

    def handle(self, *a, **o):
        if User.objects.filter(username="alex").exists():
            return self.stdout.write("Already seeded")
        random.seed(7)
        G = {n: AG.objects.get_or_create(name=n)[0] for n in ("admin", "teacher", "parent", "student", "accountant")}

        def person(username, name, phone, roles, lang="en", password=None):
            u = User.objects.create_user(username, first_name=name.split()[0], last_name=" ".join(name.split()[1:]), password=password)
            for r in roles:
                u.groups.add(G[r])
            Profile.objects.create(user=u, phone=phone, lang=lang)
            return u
        # Alex has four roles under one phone number -> 'Select role' screen (design Figure 3)
        alex = person("alex", "Alex Morgan", "998901000001", ["admin", "accountant"], password="demo12345")
        acc = person("accountant", "Aziza Yusupova", "998901000002", ["accountant"], password="demo12345")
        T = {n: person(u, n, ph, ["teacher"], password="demo12345") for u, n, ph in [
            ("turner", "Sophie Turner", "998902000001"), ("reed", "Daniel Reed", "998902000002"), ("bennett", "Olivia Bennett", "998902000003"),
            ("ellis", "James Ellis", "998902000004"), ("nodira", "Nodira Karimova", "998902000005")]}
        ch, yu = Branch.objects.create(name="Chilonzor"), Branch.objects.create(name="Yunusobod")
        R = {n: Room.objects.create(name=n, branch=ch, seats=seats) for n, seats in [("101", 14), ("203", 12), ("204", 12), ("205", 12), ("Lab 1", 12), ("Lab 2", 10)]}
        C = {n: Course.objects.create(name=n, monthly_fee=480000) for n in ["English", "Mathematics", "Science", "IELTS", "IT"]}
        for n in ["Russian", "Uzbek", "Turkish", "Arabic", "Children's programme"]:
            C[n] = Course.objects.create(name=n, monthly_fee=420000)
        spec = [("English A2-01", "English", "elementary", "reed", "203", [0, 3], (15, 0), 60), ("English B1-02", "English", "intermediate", "bennett", "204", [0, 2], (16, 0), 60),
                ("English B1-03", "English", "intermediate", "bennett", "204", [1, 3], (16, 0), 60), ("Mathematics A2-01", "Mathematics", "elementary", "turner", "101", [0, 2], (14, 0), 60),
                ("Mathematics B1-01", "Mathematics", "intermediate", "turner", "101", [0, 3], (17, 30), 60), ("Science B1-01", "Science", "intermediate", "ellis", "Lab 1", [0, 1], (16, 0), 90),
                ("English B2-01", "English", "advanced", "reed", "203", [0, 4], (18, 30), 60), ("IELTS 6-01", "IELTS", "advanced", "reed", "205", [2], (16, 0), 90)]
        groups = []
        for name, course, lvl, tch, room, days, (hh, mm), dur in spec:
            g = Group.objects.create(name=name, course=C[course], level=lvl, teacher=T[next(n for n in T if T[n].username == tch)], room=R[room], branch=ch, kind="standard")
            groups.append((g, days, hh, mm, dur))
        it = Group.objects.create(name="IT Basics B1-01", course=C["IT"], level="intermediate", teacher=T["Nodira Karimova"], room=R["Lab 2"], branch=ch)
        Group.objects.create(name="Russian A2-01", course=C["Russian"], level="elementary", teacher=T["Daniel Reed"], branch=yu, kind="mini")
        # ---- students and parents
        today = timezone.localdate()
        month = today.replace(day=1)
        prev = (month - timedelta(days=1)).replace(day=1)
        N, used, students = o["students"], set(), []
        parent_by_phone, first_pay = {}, []
        for i in range(N):
            while True:
                nm = f"{random.choice(FIRST)} {random.choice(LAST)}"
                if nm not in used:
                    used.add(nm); break
            g = groups[i % 8][0]
            if i == 0: nm, g = "Leo Wilson", groups[1][0]
            if i == 8: nm, g = "Emma Wilson", groups[1][0]
            phone = "998905000001" if i in (0, 8) else f"9989050{i + 100:05d}"
            if phone not in parent_by_phone:
                parent_by_phone[phone] = person(f"p{phone}", f"{'Grace' if i in (0,8) else 'Parent'} {nm.split()[1]}", phone, ["parent"], lang="uz" if i % 3 == 0 else "en")
            su = person(f"s{i}", nm, "998906000001" if i == 1 else None, ["student"])
            s = Student(user=su, parent=parent_by_phone[phone], name=nm, group=g, contract_number=f"ITM-2026-{i + 1:04d}", contract_date=today - timedelta(days=60))
            s.contract_scan.save(f"c{i}.pdf", ContentFile(b"%PDF-1.4 demo"), save=False)
            s.save()
            students.append(s)
            for mth in (prev, month):
                Fee.objects.create(student=s, month=mth, amount=g.fee)
            first_pay.append(Payment.objects.create(student=s, amount=g.fee, method=random.choice(["cash", "card", "payme", "click"]), reference="", received_by=acc).pk)
            if i % 5 != 0:
                Payment.objects.create(student=s, amount=g.fee, method="cash", received_by=acc)
        # backdate the October payment so it counts for last month
        old = timezone.now() - timedelta(days=45)
        Payment.objects.filter(pk__in=first_pay).update(created_at=old)
        # ---- lessons: last week, this week, next week
        mon = today - timedelta(days=today.weekday())
        tz = timezone.get_current_timezone()
        for wk in (-1, 0, 1):
            for g, days, hh, mm, dur in groups:
                for d in days:
                    day = mon + timedelta(days=7 * wk + d)
                    start = timezone.make_aware(datetime.combine(day, time(hh, mm)), tz)
                    l = Lesson.objects.create(group=g, start=start, duration=dur, room=g.room)
                    if wk == -1 or (wk == 0 and start < timezone.now() - timedelta(hours=1)):
                        l.topic = f"Unit {random.randint(1, 8)}"; l.homework = "Exercises 1-5"; l.homework_due = day + timedelta(days=3)
                        l.attendance_saved_at = start + timedelta(minutes=50); l.save()
                        for s in g.students.all():
                            Attendance.objects.create(lesson=l, student=s, status=random.choices(["present", "late", "absent"], [88, 6, 6])[0])
        # deliberate demo cases
        thu = timezone.make_aware(datetime.combine(mon + timedelta(days=10), time(17, 30)), tz)   # next Thursday: room clash like the design
        Lesson.objects.create(group=groups[3][0], start=thu, duration=60, room=R["101"])
        Lesson.objects.create(group=groups[1][0], start=timezone.make_aware(datetime.combine(mon + timedelta(days=11), time(17, 30)), tz), duration=60, room=R["204"], is_makeup=True)
        now = timezone.now()
        Lesson.objects.create(group=it, start=now + timedelta(minutes=10), duration=60, room=R["Lab 2"])    # form open right now
        Lesson.objects.create(group=it, start=now - timedelta(minutes=95), duration=60, room=R["Lab 2"])    # missing-attendance report
        Lesson.objects.create(group=it, start=now + timedelta(days=1, hours=1), duration=60, room=R["Lab 2"])
        for i, nm in enumerate(["Bobur Ismoilov", "Nigora Safarova", "Otabek Yusupov"]):
            su = person(f"it{i}", nm, None, ["student"])
            s = Student(user=su, parent=parent_by_phone.get("998905000001") if i == 0 else None, name=nm, group=it, contract_number=f"ITM-2026-9{i}", contract_date=today)
            s.contract_scan.save(f"c9{i}.pdf", ContentFile(b"%PDF-1.4 demo"), save=False); s.save()
            Fee.objects.create(student=s, month=month, amount=it.fee)
        TeacherAbsence.objects.create(teacher=T["Olivia Bennett"], start_date=today + timedelta(days=1), end_date=today + timedelta(days=7), reason="Sick leave", created_by=alex)
        # ---- applicants
        mk = lambda **k: Applicant.objects.create(parent_phone=k.pop("pp"), **k)
        mia = mk(name="Mia Chen", age=13, phone="998909000001", parent_name="Grace Chen", pp="998900001448", course=C["English"], level="intermediate", status="in_progress",
                 placement_score=78, test_date=today - timedelta(days=5), conversation_result="accepted", trial_attended=True, feedback="wants_join")
        mk(name="Kamola Rustamova", age=14, parent_name="Dilfuza Rustamova", pp="998901112233", course=C["Mathematics"], status="new")
        mk(name="Rustam Aliev", age=13, parent_name="Sanjar Aliev", pp="998902223344", course=C["English"], level="elementary", status="in_progress", placement_score=40, test_date=today)
        for i, nm in enumerate(["Dilshod", "Laylo", "Murod", "Gavhar"]):
            mk(name=f"{nm} Tashkentov", age=12 + i, pp=f"99890333000{i}", course=C["Russian"], level="elementary", kind="mini", status="waiting", placement_score=35 + i, test_date=today - timedelta(days=i))
        for i, nm in enumerate(["Aziza", "Timur"]):      # standard-group waiting list: 2 of 6 needed, no alert yet
            mk(name=f"{nm} Karimova", age=15, pp=f"99890777000{i}", course=C["English"], level="advanced", kind="standard", status="waiting", placement_score=88, test_date=today)
        lost = mk(name="Sherzod Qodirov", age=16, pp="998904445566", course=C["IELTS"], level="advanced", status="lost", lost_reason="price", follow_up=True)
        self.stdout.write(f"Seeded {Student.objects.count()} students. Sign in by phone: +998 90 100 00 01 (Alex: administrator + accountant), "
                          f"+998 90 200 00 05 (teacher Nodira), +998 90 500 00 01 (parent Grace Wilson), +998 90 600 00 01 (student). "
                          f"Demo mode shows the SMS code on screen.")
