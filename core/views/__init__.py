"""Views grouped by sub-system (see the UML architecture diagram)."""

from .academic import groups, overview, reports, schedule, substitute  # noqa: F401
from .auth import choose_role, home, login_view, logout_view, set_language, verify  # noqa: F401
from .enrolment import applicant, enrolment  # noqa: F401
from .finance import debtors, finance, open_student, pay, receipt  # noqa: F401
from .portal import absence, attendance, children, dash, fschedule, grades, materials, payments  # noqa: F401
from .teacher import leave, service_worker, sync_attendance, tatt, teacher  # noqa: F401
