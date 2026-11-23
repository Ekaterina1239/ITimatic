from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from core import views as v, views_fin as f, views_auth as au

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", v.dashboard, name="dashboard"),
    # sign in (Figures 1-3)
    path("login/", au.login_phone, name="login_phone"),
    path("login/verify/", au.login_verify, name="login_verify"),
    path("login/role/", au.select_role, name="select_role"),
    path("logout/", au.logout_view, name="logout"),
    path("lang/<str:code>/", au.set_lang, name="lang"),
    path("sw.js", v.service_worker, name="sw"),
    path("search/", v.global_search, name="search"),
    path("notifications/", v.notifications, name="notifications"),
    # enrolment (UC-1 / FR-01)
    path("enrolment/", v.applicants, name="applicants"),
    path("enrolment/new/", v.applicant_new, name="applicant_new"),
    path("enrolment/<int:pk>/", v.applicant_detail, name="applicant_detail"),
    path("followup/", v.followup, name="followup"),
    # groups / schedule / teacher absence (UC-4)
    path("groups/", v.groups, name="groups"),
    path("groups/new/", v.group_new, name="group_new"),
    path("groups/<int:pk>/", v.group_detail, name="group_detail"),
    path("schedule/", v.schedule, name="schedule"),
    path("lessons/new/", v.lesson_new, name="lesson_new"),
    path("teacher-absence/", v.teacher_absence, name="teacher_absence"),
    # attendance (UC-2 / FR-02 / FR-03)
    path("attendance/", v.attendance_app, name="attendance_app"),
    path("lessons/<int:pk>/", v.lesson_attendance, name="lesson"),
    path("api/roster/", v.api_roster, name="api_roster"),
    path("api/push/", v.api_push, name="api_push"),
    path("reports/missing/", v.missing, name="missing"),
    path("reports/", v.reports, name="reports"),
    # personal account (UC-5 / FR-05) + absence (FR-03)
    path("account/", v.records, name="records"),
    path("absence/<int:student>/", v.absence_choose, name="absence_choose"),
    path("absence/<int:student>/<int:lesson>/", v.absence_form, name="absence_form"),
    # money (UC-3 / FR-04)
    path("students/", f.students, name="students"),
    path("students/<int:pk>/finance/", f.student_finance, name="student_finance"),
    path("students/<int:pk>/discount/", f.discount_request, name="discount_request"),
    path("finance/", f.finance_report, name="finance"),
    path("payments/new/", f.payment_new, name="payment_new"),
    path("payments/<int:pk>/receipt/", f.receipt, name="receipt"),
    path("discounts/", f.discounts, name="discounts"),
    path("debtors/", f.debtors, name="debtors"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
