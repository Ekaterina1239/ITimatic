import re
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

LEVELS = [("beginner", "Beginner"), ("elementary", "Elementary"),
          ("intermediate", "Intermediate"), ("advanced", "Advanced")]
KINDS = [("standard", "Standard group"), ("mini", "Mini group"), ("individual", "Individual")]
CAPACITY = {"standard": 12, "mini": 4, "individual": 1}                     # FR-01
LOST_REASONS = [("price", "Price"), ("schedule", "Schedule"), ("level", "Level"),
                ("location", "Location"), ("other", "Other")]


def normalize_phone(p):
    d = re.sub(r"\D", "", p or "")
    return "998" + d if len(d) == 9 else d


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    lang = models.CharField(max_length=2, default="uz")

    def save(self, *a, **kw):
        self.phone = normalize_phone(self.phone) or None
        super().save(*a, **kw)


class Branch(models.Model):
    name = models.CharField(max_length=60)

    def __str__(self):
        return self.name


class Course(models.Model):
    name = models.CharField(max_length=100)
    monthly_fee = models.BigIntegerField(default=0, help_text="so'm")

    def __str__(self):
        return self.name


class Room(models.Model):
    name = models.CharField(max_length=50)
    seats = models.PositiveSmallIntegerField(default=12, help_text="physical seats in the room")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return self.name


class Group(models.Model):
    name = models.CharField(max_length=100)
    course = models.ForeignKey(Course, on_delete=models.PROTECT)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    level = models.CharField(max_length=20, choices=LEVELS)
    kind = models.CharField(max_length=12, choices=KINDS, default="standard")
    teacher = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                limit_choices_to={"groups__name": "teacher"})
    room = models.ForeignKey(Room, null=True, blank=True, on_delete=models.SET_NULL)
    monthly_fee = models.BigIntegerField(null=True, blank=True, help_text="so'm, empty = course fee")

    class Meta:
        indexes = [models.Index(fields=["course", "level"])]

    def __str__(self):
        return self.name

    @property
    def capacity(self):
        """Derived: the limit of the group type (12 / 4 / 1), but never more than the seats of the room."""
        limit = CAPACITY[self.kind]
        return min(limit, self.room.seats) if self.room_id else limit

    @property
    def size(self):
        return self.students.filter(active=True).count()

    @property
    def places_left(self):
        return max(self.capacity - self.size, 0)

    @property
    def fee(self):
        return self.monthly_fee if self.monthly_fee is not None else self.course.monthly_fee


class Applicant(models.Model):
    """FR-01 stages: level test -> teacher conversation -> trial lesson -> student feedback -> contract -> group."""
    STATUS = [("new", "New"), ("in_progress", "In Progress"), ("waiting", "Waiting list"),
              ("completed", "Completed"), ("lost", "Lost")]
    CONV = [("accepted", "Accepted"), ("not_suitable", "Not suitable")]
    FEEDBACK = [("wants_join", "Wants to join"), ("another_group", "Wants another group"), ("declines", "Declines")]
    name = models.CharField(max_length=120)
    age = models.PositiveIntegerField()
    phone = models.CharField(max_length=30, blank=True)
    parent_name = models.CharField(max_length=120, blank=True)
    parent_phone = models.CharField(max_length=30)
    course = models.ForeignKey(Course, on_delete=models.PROTECT)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    level = models.CharField(max_length=20, choices=LEVELS, default="beginner")
    kind = models.CharField(max_length=10, choices=[("standard", "Standard group"), ("mini", "Mini group")], default="standard")
    status = models.CharField(max_length=20, choices=STATUS, default="new", db_index=True)
    placement_score = models.PositiveIntegerField(null=True, blank=True,
                                                  validators=[MinValueValidator(0), MaxValueValidator(100)])
    test_date = models.DateField(null=True, blank=True)
    placement_skipped = models.BooleanField(default=False)
    skip_reason = models.CharField(max_length=200, blank=True)
    conversation_result = models.CharField(max_length=15, choices=CONV, blank=True)
    conversation_note = models.TextField(blank=True)
    trial_attended = models.BooleanField(null=True, blank=True)
    feedback = models.CharField(max_length=15, choices=FEEDBACK, blank=True)
    contract_prepared = models.BooleanField(default=False)
    contract_number = models.CharField(max_length=40, blank=True)
    contract_date = models.DateField(null=True, blank=True)
    contract_scan = models.FileField(upload_to="contracts/", null=True, blank=True)
    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL, related_name="applicants")
    lost_reason = models.CharField(max_length=12, choices=LOST_REASONS, blank=True)
    lost_note = models.TextField(blank=True)
    follow_up = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def code(self):
        return f"{self.course.name[:2].upper()}-{1000 + self.pk}"

    @property
    def suggested_contract_number(self):
        return f"ITM-{timezone.localdate().year}-{1000 + self.pk}"

    @property
    def placement_done(self):
        return self.placement_score is not None or self.placement_skipped

    @property
    def contract_done(self):
        return bool(self.contract_number and self.contract_date and self.contract_scan)

    @property
    def stage(self):
        """Current stage 1..6 (6 = add to group)."""
        if not self.placement_done: return 1
        if self.conversation_result != "accepted": return 2
        if self.trial_attended is not True: return 3
        if self.feedback != "wants_join": return 4
        if not self.contract_done: return 5
        return 6


class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="student")
    parent = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    name = models.CharField(max_length=120)
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="students")
    applicant = models.OneToOneField(Applicant, null=True, blank=True, on_delete=models.SET_NULL)
    contract_number = models.CharField(max_length=40)
    contract_date = models.DateField(null=True)
    contract_scan = models.FileField(upload_to="contracts/")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *a, **kw):
        # FR-01: a student cannot join a group without a contract
        if not (self.contract_number and self.contract_scan):
            raise ValidationError("A student cannot join a group without a signed contract.")
        super().save(*a, **kw)


class Lesson(models.Model):
    STATUS = [("scheduled", "Scheduled"), ("cancelled", "Cancelled")]
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="lessons")
    start = models.DateTimeField(db_index=True)
    duration = models.PositiveIntegerField(default=60, help_text="minutes")
    room = models.ForeignKey(Room, null=True, blank=True, on_delete=models.SET_NULL)
    substitute = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="substituting")
    status = models.CharField(max_length=10, choices=STATUS, default="scheduled")
    cancel_reason = models.CharField(max_length=200, blank=True)
    is_makeup = models.BooleanField(default=False)
    topic = models.CharField(max_length=200, blank=True)
    homework = models.TextField(blank=True)
    homework_due = models.DateField(null=True, blank=True)
    attendance_saved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["start"]

    def __str__(self):
        return f"{self.group.name} {timezone.localtime(self.start):%d.%m %H:%M}"

    @property
    def teacher(self):
        return self.substitute or self.group.teacher

    @property
    def end(self):
        return self.start + timedelta(minutes=self.duration)

    @property
    def opens_at(self):
        return self.start - timedelta(minutes=settings.ATTENDANCE_OPENS_MIN)

    @property
    def closes_at(self):                      # FR-02: read-only after 23:59 of the lesson day
        return timezone.localtime(self.start).replace(hour=23, minute=59, second=59, microsecond=0)

    @property
    def form_open(self):
        return self.opens_at <= timezone.now() <= self.closes_at

    @property
    def overdue(self):
        return (self.status == "scheduled" and self.attendance_saved_at is None and
                timezone.now() > self.start + timedelta(minutes=settings.ATTENDANCE_OVERDUE_MIN))


class HomeworkFile(models.Model):                # FR-02: up to 3 attachments
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="homework/")


class Attendance(models.Model):
    STATUS = [("present", "Present"), ("late", "Late"), ("absent", "Absent")]
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="attendance")
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS)

    class Meta:
        unique_together = ("lesson", "student")


class PreAbsence(models.Model):                  # FR-03
    LATE_MINUTES = (5, 10, 15, 30, 60)
    REASONS = [("illness", "Illness"), ("family", "Family"), ("travel", "Travel"),
               ("exam", "School exam"), ("other", "Other")]
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="pre_absences")
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    kind = models.CharField(max_length=6, choices=[("late", "Late"), ("absent", "Absent")])
    minutes = models.PositiveIntegerField(null=True, blank=True)
    reason = models.CharField(max_length=12, choices=REASONS, blank=True)
    note = models.CharField(max_length=200, blank=True)
    set_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)

    class Meta:
        unique_together = ("lesson", "student")


class Fee(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="fees")
    month = models.DateField()                   # first day of the month = due date
    amount = models.BigIntegerField()
    discount = models.BigIntegerField(default=0)

    class Meta:
        unique_together = ("student", "month")
        ordering = ["month"]

    @property
    def net(self):
        return max(self.amount - self.discount, 0)


class Payment(models.Model):                     # UC-3
    METHODS = [("cash", "Cash"), ("card", "Card"), ("payme", "Payme"), ("click", "Click")]
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="payments")
    amount = models.BigIntegerField(validators=[MinValueValidator(1)])
    method = models.CharField(max_length=10, choices=METHODS)
    reference = models.CharField(max_length=80, blank=True)
    received_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    @property
    def receipt_no(self):
        return f"R-{self.pk:06d}"


class DiscountRequest(models.Model):             # UC-3: discount must be requested by the accountant, approved by the administrator
    STATUS = [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")]
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    fee = models.ForeignKey(Fee, on_delete=models.CASCADE)
    amount = models.BigIntegerField(validators=[MinValueValidator(1)])
    reason = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=STATUS, default="pending")
    requested_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DebtorNote(models.Model):                  # FR-04
    OUTCOMES = [("promised", "Promised by"), ("no_answer", "No answer"), ("leaving", "Leaving")]
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="debtor_notes")
    month = models.DateField()
    outcome = models.CharField(max_length=10, choices=OUTCOMES)
    promised_by = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class TeacherAbsence(models.Model):              # UC-4
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name="absences")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    template = models.CharField(max_length=200)
    params = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]


class SMSLog(models.Model):                      # prototype stand-in for an SMS gateway
    phone = models.CharField(max_length=15)
    text = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)


class LoginCode(models.Model):                   # UC-5
    phone = models.CharField(max_length=15, db_index=True)
    code_hash = models.CharField(max_length=64)
    attempts = models.PositiveIntegerField(default=0)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class SyncLog(models.Model):
    uuid = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE)
    outcome = models.CharField(max_length=20, default="ok")
    received_at = models.DateTimeField(auto_now_add=True)
