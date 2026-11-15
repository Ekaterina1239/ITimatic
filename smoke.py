import os, django, datetime as dt

os.environ["DJANGO_SETTINGS_MODULE"] = "itmatic.settings"
django.setup()
from django.conf import settings

settings.ALLOWED_HOSTS = ["*"]
from django.test import Client
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import *
from django.test.utils import setup_test_environment

setup_test_environment()


def login(phone, role=None):
    c = Client()
    assert c.post("/", {"phone": phone}).status_code == 302
    assert c.post("/verify/", {"code": "000000"}).status_code == 200
    r = c.post("/verify/", {"code": "482619"})
    if r.url == "/role/":
        c.post("/role/", {"role": role})
    return c


def get(c, *urls):
    for u in urls:
        x = c.get(u)
        assert x.status_code == 200, (u, x.status_code, x.content[:300])


today = timezone.localdate()
g = Group.objects.get(name="English B1-02")
emma = Student.objects.get(name="Emma Wilson")
# parent flow
p = login("902222222")
assert p.get("/home/").url == "/children/"
get(p, "/children/")
assert p.post("/children/", {"child": emma.pk}).url == "/dash/"
get(
    p,
    "/dash/",
    "/my-schedule/",
    "/my-schedule/?w=1",
    "/absence/",
    "/attendance/",
    "/attendance/?subject=English",
    "/grades/",
    "/materials/",
    "/payments/",
)
past = Lesson.objects.filter(group=g, date__lt=today).first()
r = p.post("/absence/", {"lesson": past.pk, "reason": "Illness"})
print("started lesson blocked:", b"already started" in r.content)
up = [
    l
    for l in Lesson.objects.filter(group=g, date__gte=today)
    if l.start_dt > timezone.now()
][0]
r = p.post("/absence/", {"lesson": up.pk, "reason": "Other"})
print("Other needs note:", b"short note" in r.content)
p.post("/absence/", {"lesson": up.pk, "reason": "Family"})
print(
    "reported shown:",
    b"Reported"
    in p.get(
        "/my-schedule/?w=%d"
        % ((up.date - (today - dt.timedelta(days=today.weekday()))).days // 7)
    ).content,
)
pay = emma.payments.first()
print(
    "receipt:",
    p.get(f"/receipt/{pay.pk}/").status_code,
    p.get(f"/receipt/{pay.pk}/?dl=1")["Content-Disposition"][:20],
)
s = login("903333333")
get(s, "/dash/", "/my-schedule/", "/grades/")
# teacher flow
t = login("901111111")
get(t, "/teacher/", "/leave/")
l = (
    Lesson.objects.get(
        group=g, date__gt=today - dt.timedelta(days=4), date__lte=today, topic=""
    )
    if Lesson.objects.filter(group=g, date=today).exists()
    else Lesson.objects.filter(group=g).last()
)
get(t, f"/lesson/{l.pk}/", "/teacher/?d=%s" % l.date)
t.post(
    f"/lesson/{l.pk}/",
    {"topic": "Unit 4", "homework": "Story", "draft": "1", "s%d" % emma.pk: "late"},
)
print("draft:", Lesson.objects.get(pk=l.pk).draft)
t.post(f"/lesson/{l.pk}/", {"topic": "Unit 4", "submit": "1"})
print("completed:", Lesson.objects.get(pk=l.pk).completed)
t.post(
    "/leave/",
    {
        "start": str(today),
        "end": str(today + dt.timedelta(days=14)),
        "reason": "Sick leave",
    },
)
# admin flow
a = login("900001448", "admin")
get(
    a,
    "/overview/",
    "/enrolment/?q=Mia",
    "/enrolment/?stage=Agreement",
    "/debtors/",
    "/debtors/?q=Lucas",
    "/pay/?student=%d" % Student.objects.get(name="Lucas Martin").pk,
    "/groups/",
    "/groups/?s=closed",
)
r = a.post(
    "/enrolment/", {"name": "Test Kid", "phone": "+998 90 111 11 11", "subject": "IT"}
)
print("enquiry created:", Applicant.objects.filter(name="Test Kid").exists())
lm = Student.objects.get(name="Lucas Martin")
before = len(a.get("/debtors/").context["rows"])
r = a.post(
    "/pay/",
    {"student": lm.pk, "amount": "480000", "method": "Cash", "date": str(today)},
)
print("receipt on same screen:", b"ITM-2026" in r.content, "stat:", r.context["stat"])
print("debtors shrank:", len(a.get("/debtors/").context["rows"]) < before)
q = LeaveRequest.objects.first()
a.post("/groups/", {"act": "leave", "req": q.pk, "d": "approve"})
print("lessons flagged:", Lesson.objects.filter(needs_sub=True).count() > 0)
dan = User.objects.get(phone="901111112")
nl = Lesson.objects.filter(needs_sub=True).first()
a.post("/groups/", {"act": "sub", "g": nl.group_id, "lesson": nl.pk, "teacher": dan.pk})
print(
    "substitute visible to Daniel:",
    login("901111112").get("/teacher/?d=%s" % nl.date).content.count(b"Substitute") > 0,
)
a.post(
    "/groups/",
    {
        "act": "create",
        "name": "IT A1-01",
        "course": "IT",
        "level": "A1",
        "capacity": "10",
    },
)
ng = Group.objects.get(name="IT A1-01")
a.post("/groups/", {"act": "archive", "g": ng.pk})
print("archived:", Group.objects.get(pk=ng.pk).status)
d = login("900001448", "director")
get(d, "/overview/", "/debtors/", "/groups/")
ac = login("900001448", "accountant")
get(ac, "/debtors/", "/pay/", "/finance/")

# ---- NFR-02: interface languages -------------------------------------------
import json, re
from django.utils import timezone as tz

par = login("902222222")
par.post("/children/", {"child": emma.pk})
par.post("/language/", {"language": "ru", "next": "/dash/"})
print("language saved on account:", User.objects.get(phone="902222222").language == "ru")
again = login("902222222")  # new device / new session
again.post("/children/", {"child": emma.pk})
html = again.get("/dash/").content.decode()
print("russian after re-login:", "Посещаемость" in html and "Attendance</h3>" not in html)
print("date format DD.MM.YYYY:", bool(re.search(r"\d{2}\.\d{2}\.\d{4}", again.get("/payments/").content.decode())))
print("currency is so‘m:", "so‘m" in html)
for lang, word in (("uz", "Davomat"), ("en", "Attendance")):
    again.post("/language/", {"language": lang})
    assert word in again.get("/dash/").content.decode(), lang
pages = {
    "900001448": ("admin", ["/overview/", "/enrolment/", "/applicant/%d/" % Applicant.objects.first().pk, "/schedule/", "/groups/", "/debtors/", "/finance/", "/reports/", "/pay/"]),
    "901111111": (None, ["/teacher/", "/leave/", "/lesson/%d/" % Lesson.objects.filter(group=g).first().pk, "/reports/"]),
    "902222222": (None, ["/dash/", "/my-schedule/", "/absence/", "/attendance/", "/grades/", "/materials/", "/payments/", "/children/"]),
}
for lang in ("ru", "uz"):
    for phone, (role, urls) in pages.items():
        c = login(phone, role)
        if phone == "902222222":
            c.post("/children/", {"child": emma.pk})
        c.post("/language/", {"language": lang})
        get(c, *urls)
    User.objects.update(language="en")
print("all pages render in ru and uz: True")

# ---- NFR-03: offline attendance batch ---------------------------------------
t = login("901111111")
lesson = Lesson.objects.filter(group=g, substitute__isnull=True).first()
ids = list(g.students.values_list("id", flat=True))
recorded = (tz.now() - dt.timedelta(minutes=40)).isoformat()
batch = {"lesson": lesson.pk, "marks": {str(i): "present" for i in ids}, "topic": "Offline topic",
         "homework": "", "due": "", "submit": True, "recorded_at": recorded}
r = t.post("/api/attendance/sync/", json.dumps(batch), content_type="application/json")
a = Attendance.objects.filter(lesson=lesson).first()
print("offline batch accepted:", r.json()["ok"], "two times kept:", a.was_offline)
broken = dict(batch, marks={str(i): "present" for i in ids[:-1]})  # one student missing
r = t.post("/api/attendance/sync/", json.dumps(broken), content_type="application/json")
print("incomplete batch rejected whole:", r.status_code == 409)
r = t.post("/api/attendance/sync/", "{not json", content_type="application/json")
print("garbage rejected:", r.status_code == 400)
print("service worker served:", t.get("/sw.js")["Content-Type"].startswith("application/javascript"))

# ---- bug fix: changing the room only checks, it does not confirm -------------
adm = login("900001448", "admin")
free = Lesson.objects.filter(substitute__isnull=True, cancelled=False).last()
adm.get("/substitute/%d/?room=101" % free.pk)
print("room change does not confirm:", Lesson.objects.get(pk=free.pk).substitute_id is None)
print("ALL OK")
