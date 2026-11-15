from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from . import models as M

admin.site.register(M.User, UserAdmin)
for m in [
    M.Branch,
    M.UserRole,
    M.Group,
    M.Student,
    M.Applicant,
    M.Lesson,
    M.Attendance,
    M.AbsenceReport,
    M.Charge,
    M.Payment,
    M.Certificate,
    M.Notification,
]:
    admin.site.register(m)
