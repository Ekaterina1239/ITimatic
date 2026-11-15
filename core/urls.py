from django.urls import path

from . import views as v

urlpatterns = [
    # Accounts
    path("", v.login_view, name="login"),
    path("verify/", v.verify, name="verify"),
    path("role/", v.choose_role, name="role"),
    path("logout/", v.logout_view, name="logout"),
    path("home/", v.home, name="home"),
    path("language/", v.set_language, name="set_language"),
    # Parent / student portal
    path("children/", v.children, name="children"),
    path("dash/", v.dash, name="dash"),
    path("my-schedule/", v.fschedule, name="fschedule"),
    path("absence/", v.absence, name="absence"),
    path("attendance/", v.attendance, name="attendance"),
    path("grades/", v.grades, name="grades"),
    path("materials/", v.materials, name="materials"),
    path("payments/", v.payments, name="payments"),
    path("receipt/<int:pk>/", v.receipt, name="receipt"),
    # Teacher
    path("teacher/", v.teacher, name="teacher"),
    path("lesson/<int:pk>/", v.tatt, name="tatt"),
    path("leave/", v.leave, name="leave"),
    path("api/attendance/sync/", v.sync_attendance, name="sync_attendance"),
    path("sw.js", v.service_worker, name="service_worker"),
    # Enrolment
    path("enrolment/", v.enrolment, name="enrolment"),
    path("applicant/<int:pk>/", v.applicant, name="applicant"),
    # Academic
    path("overview/", v.overview, name="overview"),
    path("groups/", v.groups, name="groups"),
    path("schedule/", v.schedule, name="schedule"),
    path("substitute/<int:pk>/", v.substitute, name="substitute"),
    path("reports/", v.reports, name="reports"),
    # Finance
    path("debtors/", v.debtors, name="debtors"),
    path("student/<int:pk>/", v.open_student, name="open_student"),
    path("pay/", v.pay, name="pay"),
    path("finance/", v.finance, name="finance"),
]
