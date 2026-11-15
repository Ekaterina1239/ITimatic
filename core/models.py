"""Domain model of the ITmatic Learning Center information system.

The classes are grouped by sub-system (the same packages are used in the
UML architecture diagram):

* Accounts       - User, UserRole, Branch
* Enrolment      - Applicant
* Academic       - Group, Student, Lesson, Attendance, AbsenceReport,
                   Assessment, Certificate
* Finance        - MonthlyAmount (abstract), Charge, Payment
* Staff          - LeaveRequest
* Notifications  - Notification
"""

import datetime as dt

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

ROLES = [
    ("admin", "Administrator"),
    ("teacher", "Teacher"),
    ("parent", "Parent"),
    ("student", "Student"),
    ("edmgr", "Education manager"),
    ("accountant", "Accountant"),
    ("director", "Director"),
]
LANGUAGES = [("en", "English"), ("ru", "Русский"), ("uz", "O‘zbekcha")]
STAGES = [
    "Enquiry",
    "Assessment",
    "Group matching",
    "Trial booked",
    "Trial completed",
    "Agreement",
    "Confirmed",
    "Lost",
]


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------
class User(AbstractUser):
    """Any person who signs in by phone. One person may hold several roles."""

    phone = models.CharField(max_length=9, unique=True, null=True)
    # NFR-02: the last chosen interface language is remembered per account.
    language = models.CharField(max_length=2, choices=LANGUAGES, default="en")

    def role_codes(self):
        return list(self.roles.values_list("role", flat=True))


class Branch(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name

    def active_groups(self):
        return self.group_set.filter(active=True)


class UserRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="roles")
    role = models.CharField(max_length=12, choices=ROLES)

    class Meta:
        unique_together = ("user", "role")


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------
class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notes")
    kind = models.CharField(max_length=20)
    text = models.CharField(max_length=250)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    @classmethod
    def send(cls, user, kind, text):
        if user is not None:
            return cls.objects.create(user=user, kind=kind, text=text)


# --------------------------------------------------------------------------
# Academic
# --------------------------------------------------------------------------
class Group(models.Model):
    name = models.CharField(max_length=60)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    teacher = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="teaching"
    )
    course = models.CharField(max_length=40, blank=True)
    level = models.CharField(max_length=10, blank=True)
    schedule = models.CharField(max_length=60, blank=True)
    capacity = models.PositiveSmallIntegerField(default=12)
    status = models.CharField(max_length=10, default="active")  # active/closed/archived
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    @property
    def enrolled(self):
        return self.students.count()

    @property
    def free(self):
        return self.capacity - self.enrolled

    def has_place(self):
        return self.free > 0

    def close(self, archive=False):
        self.status = "archived" if archive else "closed"
        self.active = False
        self.save()

    def notify_parents(self, kind, text):
        for student in self.students.filter(parent__isnull=False):
            Notification.send(student.parent, kind, text)


class Student(models.Model):
    name = models.CharField(max_length=80)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    parent = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    user = models.OneToOneField(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="student"
    )
    group = models.ForeignKey(
        Group, null=True, blank=True, on_delete=models.SET_NULL, related_name="students"
    )
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    def attendance_pct(self):
        marked = self.attendance.exclude(status="not_marked")
        total = marked.count()
        if not total:
            return 100
        attended = marked.filter(status__in=["present", "late", "excused"]).count()
        return round(100 * attended / total)

    def payment_summary(self):
        """FR-04: allocate payments to monthly charges (oldest first)."""
        paid = sum(p.amount for p in self.payments.all())
        remaining, owed, due = paid, 0, None
        for charge in self.charges.order_by("due"):
            if remaining >= charge.amount:
                remaining -= charge.amount
            else:
                owed += charge.amount - remaining
                remaining = 0
                due = due or charge.due
        today = timezone.localdate()
        if not owed:
            status = "Paid"
        else:
            status = "Overdue" if due < today else "Due"
        return {
            "owed": owed,
            "due": due,
            "status": status,
            "days": (today - due).days if status == "Overdue" else 0,
            "paid": paid,
        }


class Lesson(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="lessons")
    date = models.DateField()
    start = models.TimeField()
    end = models.TimeField()
    room = models.CharField(max_length=20)
    substitute = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="cover"
    )
    topic = models.CharField(max_length=120, blank=True)
    homework = models.TextField(blank=True)
    homework_due = models.DateField(null=True, blank=True)
    material = models.FileField(upload_to="materials/", blank=True)
    completed = models.BooleanField(default=False)
    draft = models.BooleanField(default=False)
    needs_sub = models.BooleanField(default=False)
    cancelled = models.BooleanField(default=False)

    class Meta:
        ordering = ["date", "start"]

    def __str__(self):
        return f"{self.group} {self.date:%d.%m.%Y} {self.start:%H:%M}"

    @property
    def start_dt(self):
        return timezone.make_aware(dt.datetime.combine(self.date, self.start))

    def has_started(self):
        return self.start_dt <= timezone.now()

    @property
    def teacher_on_duty(self):
        return self.substitute or self.group.teacher

    def taught_by(self, user):
        if self.substitute_id:
            return self.substitute_id == user.id
        return self.group.teacher_id == user.id

    def clash(self, room=None):
        """Return another lesson that already occupies the room at this time."""
        return (
            Lesson.objects.filter(
                date=self.date,
                room=room or self.room,
                cancelled=False,
                start__lt=self.end,
                end__gt=self.start,
            )
            .exclude(pk=self.pk)
            .first()
        )

    def record_attendance(self, marks, recorded_at=None):
        """FR-02 / NFR-03: save one status per student of the group as one batch.

        `marks` maps student id -> status.  The batch is rejected as a whole if
        it does not match the current group list (e.g. a student transferred
        while the teacher's device was offline).
        """
        expected = set(self.group.students.values_list("id", flat=True))
        if set(marks) != expected:
            raise ValueError("The group list has changed since this form was saved.")
        now = timezone.now()
        for student_id, status in marks.items():
            Attendance.objects.update_or_create(
                lesson=self,
                student_id=student_id,
                defaults={
                    "status": status,
                    "recorded_at": recorded_at or now,
                    "synced_at": now,
                },
            )


class Attendance(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="att")
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="attendance"
    )
    status = models.CharField(max_length=12, default="not_marked")
    # NFR-03: when the teacher marked it and when it reached the server.
    recorded_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("lesson", "student")

    @property
    def was_offline(self):
        return bool(
            self.recorded_at
            and self.synced_at
            and (self.synced_at - self.recorded_at).total_seconds() > 60
        )


class AbsenceReport(models.Model):
    """FR-03: a parent reports an absence before the lesson starts."""

    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE)
    kind = models.CharField(max_length=6)
    reason = models.CharField(max_length=20, blank=True)
    note = models.CharField(max_length=200, blank=True)
    minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    until = models.DateField(null=True, blank=True)
    withdrawn = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    def withdraw(self):
        """The parent cancels the report (the student will come after all)."""
        self.withdrawn = True
        self.save(update_fields=["withdrawn"])


class Assessment(models.Model):
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="assessments"
    )
    subject = models.CharField(max_length=40)
    name = models.CharField(max_length=80)
    date = models.DateField()
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    max_score = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["-date"]

    def percent(self):
        if self.score is None:
            return None
        return round(100 * self.score / self.max_score)


class Certificate(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    score = models.PositiveSmallIntegerField()
    attendance = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, default="eligible")
    # eligible -> submitted -> approved / rejected

    def submit(self):
        self.status = "submitted"
        self.save()

    def decide(self, decision):
        if self.status != "submitted" or decision not in ("approved", "rejected"):
            return
        self.status = decision
        self.save()
        if decision == "rejected":
            Notification.send(
                self.group.teacher,
                "certificate",
                f"Certificate for {self.student.name} was rejected.",
            )


# --------------------------------------------------------------------------
# Enrolment
# --------------------------------------------------------------------------
class Applicant(models.Model):
    """FR-01: one enquiry moving through the enrolment stages."""

    name = models.CharField(max_length=80)
    parent_name = models.CharField(max_length=80, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    subject = models.CharField(max_length=40)
    level = models.CharField(max_length=10)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    assigned = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    stage = models.CharField(max_length=20, default="Enquiry")
    test_date = models.DateField(null=True, blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    skip_reason = models.CharField(max_length=120, blank=True)
    rec_level = models.CharField(max_length=10, blank=True)
    conv = models.CharField(max_length=12, blank=True)
    trial = models.CharField(max_length=12, blank=True)
    feedback = models.CharField(max_length=20, blank=True)
    contract_status = models.CharField(max_length=12, blank=True)
    contract_no = models.CharField(max_length=30, blank=True)
    signing_date = models.DateField(null=True, blank=True)
    scan = models.FileField(upload_to="contracts/", blank=True)
    contract_recorded = models.BooleanField(default=False)
    waiting = models.BooleanField(default=False)
    lost_reason = models.CharField(max_length=12, blank=True)
    lost_note = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name

    def record_contract(self):
        if self.contract_no and self.signing_date and self.scan:
            self.contract_recorded = True
            self.contract_status = "Signed"
        return self.contract_recorded

    def join_group(self, group):
        """Turn the applicant into a student. Returns an error text or None."""
        if not self.contract_recorded:
            return "A signed contract is required before joining a group."
        if not group.has_place():
            return "The group is full. Move the applicant to the waiting list."
        Student.objects.create(name=self.name, branch=self.branch, group=group)
        self.stage = "Confirmed"
        self.waiting = False
        self.save()
        return None

    def mark_lost(self, reason, note=""):
        if not reason or (reason == "Other" and not note):
            return False
        self.lost_reason, self.lost_note, self.stage = reason, note, "Lost"
        return True


# --------------------------------------------------------------------------
# Finance
# --------------------------------------------------------------------------
class MonthlyAmount(models.Model):
    """Abstract parent of Charge and Payment: an amount for one student/month."""

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="%(class)ss"
    )
    month = models.DateField()
    amount = models.PositiveIntegerField()

    class Meta:
        abstract = True


class Charge(MonthlyAmount):
    due = models.DateField()

    def is_late(self, paid):
        return self.due < timezone.localdate() and paid < self.amount


class Payment(MonthlyAmount):
    method = models.CharField(max_length=13)
    discount = models.CharField(max_length=20, default="None")
    paid_on = models.DateField(null=True, blank=True)
    receipt_no = models.CharField(max_length=20, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    def issue_receipt(self):
        self.receipt_no = f"ITM-2026-{1100 + self.pk}"
        self.save()
        return self.receipt_no


# --------------------------------------------------------------------------
# Staff
# --------------------------------------------------------------------------
class LeaveRequest(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name="leaves")
    start = models.DateField()
    end = models.DateField()
    reason = models.CharField(max_length=12)
    note = models.CharField(max_length=200, blank=True)
    attachment = models.FileField(upload_to="leave/", blank=True)
    status = models.CharField(max_length=10, default="Pending")

    class Meta:
        ordering = ["-start"]

    def affected_lessons(self):
        return Lesson.objects.filter(
            group__teacher=self.teacher,
            date__range=[self.start, self.end],
            substitute__isnull=True,
            cancelled=False,
        )

    def decide(self, approve):
        self.status = "Approved" if approve else "Rejected"
        self.save()
        if approve:
            self.affected_lessons().update(needs_sub=True)
