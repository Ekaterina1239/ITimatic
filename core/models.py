"""Domain model of the ITmatic Learning Center information system.

The classes are grouped by sub-system (the same packages are used in the
UML architecture diagram):

* Accounts       - User, UserRole, Branch
* Enrolment      - Applicant, EnrolmentStep (abstract), LevelTest, TrialLesson, Contract
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

# --------------------------------------------------------------------------
# Enumerations (UML «enumeration»). The stored value is the first string.
# --------------------------------------------------------------------------
class Role(models.TextChoices):
    ADMIN = "admin", "Administrator"
    TEACHER = "teacher", "Teacher"
    PARENT = "parent", "Parent"
    STUDENT = "student", "Student"
    EDUCATION_MANAGER = "edmgr", "Education manager"
    ACCOUNTANT = "accountant", "Accountant"
    DIRECTOR = "director", "Director"


class Language(models.TextChoices):
    EN = "en", "English"
    RU = "ru", "Русский"
    UZ = "uz", "O‘zbekcha"


class EnrolmentStage(models.TextChoices):
    ENQUIRY = "Enquiry"
    ASSESSMENT = "Assessment"
    GROUP_MATCHING = "Group matching"
    TRIAL_BOOKED = "Trial booked"
    TRIAL_COMPLETED = "Trial completed"
    AGREEMENT = "Agreement"
    CONFIRMED = "Confirmed"
    LOST = "Lost"


class LostReason(models.TextChoices):
    PRICE = "Price"
    SCHEDULE = "Schedule"
    LEVEL = "Level"
    LOCATION = "Location"
    OTHER = "Other"


class Conversation(models.TextChoices):
    ACCEPTED = "Accepted"
    NOT_SUITABLE = "Not suitable"


class TrialAttendance(models.TextChoices):
    ATTENDED = "Attended"
    DID_NOT_ATTEND = "Did not attend"


class Feedback(models.TextChoices):
    WANTS_TO_JOIN = "Wants to join"
    WANTS_ANOTHER_GROUP = "Wants another group"
    DECLINES = "Declines"


class ContractStatus(models.TextChoices):
    PREPARED = "Prepared"
    SIGNED = "Signed"


class GroupStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    ARCHIVED = "archived", "Archived"


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    LATE = "late", "Late"
    ABSENT = "absent", "Absent"
    EXCUSED = "excused", "Excused"
    UNEXPLAINED = "unexplained", "Unexplained"
    NOT_MARKED = "not_marked", "Not marked"


class AbsenceKind(models.TextChoices):
    ABSENT = "absent", "Absent"
    LATE = "late", "Late"


class AbsenceReason(models.TextChoices):
    ILLNESS = "Illness"
    FAMILY = "Family"
    TRAVEL = "Travel"
    SCHOOL_EXAM = "School exam"
    OTHER = "Other"


class CertificateStatus(models.TextChoices):
    ELIGIBLE = "eligible", "Eligible"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class PaymentMethod(models.TextChoices):
    CASH = "Cash"
    CARD = "Card"
    BANK_TRANSFER = "Bank transfer"
    PAYME = "Payme"
    CLICK = "Click"


class LeaveReason(models.TextChoices):
    SICK_LEAVE = "Sick leave"
    OTHER = "Other"


class LeaveStatus(models.TextChoices):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


# kept for older imports
ROLES = Role.choices
LANGUAGES = Language.choices
STAGES = EnrolmentStage.values


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------
class User(AbstractUser):
    """Any person who signs in by phone. One person may hold several roles."""

    phone = models.CharField(max_length=9, unique=True, null=True)
    # NFR-02: the last chosen interface language is remembered per account.
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.EN)

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
    role = models.CharField(max_length=12, choices=Role.choices)

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
        """Deliver a message through every channel (in-app + SMS)."""
        from .services import notification_service

        if user is not None:
            notification_service.notify(user, kind, text)


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
    status = models.CharField(max_length=10, choices=GroupStatus.choices, default=GroupStatus.ACTIVE)
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
    status = models.CharField(max_length=12, choices=AttendanceStatus.choices, default=AttendanceStatus.NOT_MARKED)
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
    kind = models.CharField(max_length=6, choices=AbsenceKind.choices, default=AbsenceKind.ABSENT)
    reason = models.CharField(max_length=20, choices=AbsenceReason.choices, blank=True)
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
    status = models.CharField(max_length=10, choices=CertificateStatus.choices, default=CertificateStatus.ELIGIBLE)
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
    """FR-01: one enquiry moving through the enrolment stages.

    The work done at each stage is kept in its own EnrolmentStep object
    (LevelTest, TrialLesson, Contract) — composition: the steps live and die
    with the applicant.
    """

    name = models.CharField(max_length=80)
    parent_name = models.CharField(max_length=80, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    subject = models.CharField(max_length=40)
    level = models.CharField(max_length=10, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    assigned = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    stage = models.CharField(max_length=20, choices=EnrolmentStage.choices, default=EnrolmentStage.ENQUIRY)
    waiting = models.BooleanField(default=False)
    lost_reason = models.CharField(max_length=12, choices=LostReason.choices, blank=True)
    lost_note = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name

    # the three steps are created on first use
    @property
    def level_test(self):
        return LevelTest.objects.get_or_create(applicant=self)[0]

    @property
    def trial(self):
        return TrialLesson.objects.get_or_create(applicant=self)[0]

    @property
    def contract(self):
        return Contract.objects.get_or_create(applicant=self)[0]

    def steps(self):
        return [self.level_test, self.trial, self.contract]

    def progress(self):
        """How many steps are complete (polymorphic is_complete())."""
        return sum(step.is_complete() for step in self.steps())

    def join_group(self, group):
        """Turn the applicant into a student. Returns an error text or None."""
        if not self.contract.is_complete():
            return "A signed contract is required before joining a group."
        if not group.has_place():
            return "The group is full. Move the applicant to the waiting list."
        Student.objects.create(name=self.name, branch=self.branch, group=group)
        self.stage = EnrolmentStage.CONFIRMED
        self.waiting = False
        self.save()
        return None

    def mark_lost(self, reason, note=""):
        if reason not in LostReason.values or (reason == LostReason.OTHER and not note):
            return False
        self.lost_reason, self.lost_note, self.stage = reason, note, EnrolmentStage.LOST
        return True


class EnrolmentStep(models.Model):
    """Abstract parent of the three enrolment steps."""

    applicant = models.OneToOneField(Applicant, on_delete=models.CASCADE, related_name="%(class)s_step")
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def is_complete(self):
        raise NotImplementedError


class LevelTest(EnrolmentStep):
    date = models.DateField(null=True, blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    recommended_level = models.CharField(max_length=10, blank=True)
    skip_reason = models.CharField(max_length=120, blank=True)

    def is_complete(self):
        return self.score is not None or bool(self.skip_reason)

    def record(self, score, date=None, level=""):
        self.score, self.date, self.recommended_level, self.skip_reason = score, date, level, ""
        self.save()

    def skip(self, reason):
        self.score, self.skip_reason = None, reason
        self.save()


class TrialLesson(EnrolmentStep):
    conversation = models.CharField(max_length=12, choices=Conversation.choices, blank=True)
    attendance = models.CharField(max_length=14, choices=TrialAttendance.choices, blank=True)
    feedback = models.CharField(max_length=20, choices=Feedback.choices, blank=True)

    def is_complete(self):
        return bool(self.feedback)

    def outcome(self):
        return self.feedback or self.attendance or self.conversation


class Contract(EnrolmentStep):
    number = models.CharField(max_length=30, blank=True)
    signing_date = models.DateField(null=True, blank=True)
    scan = models.FileField(upload_to="contracts/", blank=True)
    status = models.CharField(max_length=10, choices=ContractStatus.choices, blank=True)

    def is_complete(self):
        return self.status == ContractStatus.SIGNED

    def prepare(self):
        self.status = ContractStatus.PREPARED
        self.save()

    def record(self, number, signing_date, scan=None):
        """A contract counts as signed only with number, date and a scan."""
        self.number, self.signing_date = number, signing_date or None
        if scan:
            self.scan = scan
        if self.number and self.signing_date and self.scan:
            self.status = ContractStatus.SIGNED
        self.save()
        return self.is_complete()


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
    method = models.CharField(max_length=13, choices=PaymentMethod.choices)
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
    reason = models.CharField(max_length=12, choices=LeaveReason.choices, default=LeaveReason.SICK_LEAVE)
    note = models.CharField(max_length=200, blank=True)
    attachment = models.FileField(upload_to="leave/", blank=True)
    status = models.CharField(max_length=10, choices=LeaveStatus.choices, default=LeaveStatus.PENDING)

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