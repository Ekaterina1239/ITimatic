"""Payments, receipts and the monthly debtors list (FR-04)."""

import datetime as dt

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from ..models import PaymentMethod, Applicant, Branch, Charge, Group, Notification, Payment, Student
from .common import role_required

PAYMENT_METHODS = PaymentMethod.values


def ledger_rows(month):
    today = timezone.localdate()
    rows = []
    for charge in Charge.objects.filter(month=month).select_related("student__group", "student__parent"):
        pays = list(charge.student.payments.filter(month=month))
        paid = sum(p.amount for p in pays)
        if paid >= charge.amount:
            status, tone = "Received", "ok"
        elif charge.due < today:
            status, tone = _("%(n)s days overdue") % {"n": (today - charge.due).days}, "bad"
        else:
            status, tone = "Scheduled", "warn"
        rows.append({"c": charge, "s": charge.student, "paid": paid, "pay": pays[-1] if pays else None,
                     "owed": max(charge.amount - paid, 0), "status": status, "tone": tone,
                     "late": charge.is_late(paid), "inv": f"INV-26{charge.pk:04d}"})
    return rows


def remind(student, month):
    if student.parent:
        Notification.send(student.parent, "payment",
                          f"Payment reminder: {student.name}’s tuition for {month:%m.%Y} is overdue. Please pay at the center or by card.")
        return True
    return False


@role_required("admin", "director", "accountant")
def finance(request):
    month = dt.date.fromisoformat(request.GET.get("month", timezone.localdate().strftime("%Y-%m")) + "-01")
    rows = ledger_rows(month)
    if request.method == "POST":
        if request.POST.get("act") == "remind_all":
            n = sum(remind(x["s"], month) for x in rows if x["late"])
            messages.success(request, _("Reminder sent to %(n)s parents.") % {"n": n})
        elif request.POST.get("act") == "remind":
            student = get_object_or_404(Student, pk=request.POST["student"])
            remind(student, month)
            messages.success(request, _("Reminder sent to the parent of %(name)s.") % {"name": student.name})
        return redirect(f"{request.path}?month={month:%Y-%m}&tab={request.GET.get('tab', 'all')}")
    tab, q = request.GET.get("tab", "all"), request.GET.get("q", "").lower()
    shown = rows
    if tab == "received":
        shown = [x for x in rows if x["tone"] == "ok"]
    elif tab == "overdue":
        shown = [x for x in rows if x["tone"] == "bad"]
    elif tab == "scheduled":
        shown = [x for x in rows if x["tone"] == "warn"]
    if q:
        shown = [x for x in shown if q in x["s"].name.lower() or (x["s"].parent and q in x["s"].parent.get_full_name().lower())]
    from django.core.paginator import Paginator
    page = Paginator(shown, 10).get_page(request.GET.get("page"))
    received = sum(x["paid"] for x in rows)
    total = sum(x["c"].amount for x in rows)
    overdue = [x for x in rows if x["tone"] == "bad"]
    upcoming = [x for x in rows if x["tone"] == "warn"]
    from .academic import monthly_collections
    from django.utils.formats import date_format
    trend = monthly_collections()
    return render(
        request,
        "finance.html",
        {
            "rows": page, "page": page, "shown_n": len(shown), "all_n": len(rows), "month": month, "tab": tab, "q": request.GET.get("q", ""),
            "received": received, "received_n": len(rows) - len(overdue) - len(upcoming), "total": total,
            "overdue": sum(x["owed"] for x in overdue), "overdue_n": len(overdue),
            "upcoming": sum(x["owed"] for x in upcoming), "upcoming_n": len(upcoming),
            "trend_vals": [v / 1_000_000 for _, v in trend], "trend_labels": ",".join(date_format(d, "M") for d, _ in trend),
            "last_reminder": Notification.objects.filter(kind="payment").order_by("-created").first(),
        },
    )


@role_required("admin", "accountant", "director")
def debtors(request):
    query, group_id = request.GET.get("q", ""), request.GET.get("group", "")
    branch = request.GET.get("branch", "Chilonzor")
    if request.method == "POST":
        student = get_object_or_404(Student, pk=request.POST["student"])
        remind(student, timezone.localdate().replace(day=1))
        messages.success(request, _("Reminder sent to the parent of %(name)s.") % {"name": student.name})
        return redirect(request.get_full_path())
    rows = []
    for student in Student.objects.select_related("group", "parent", "branch"):
        info = student.payment_summary()
        if not info["owed"] or student.branch.name != branch:
            continue
        if group_id and str(student.group_id) != group_id:
            continue
        haystack = (student.name + (student.parent.phone or "" if student.parent else "")).lower()
        if query and query.lower() not in haystack:
            continue
        last = student.payments.order_by("-paid_on").first()
        rows.append({"s": student, "last": last, **info})
    rows.sort(key=lambda r: -r["days"])
    return render(
        request,
        "debtors.html",
        {"rows": rows, "groups": Group.objects.filter(active=True), "q": query, "gp": group_id, "branch": branch,
         "branches": Branch.objects.all(), "total": sum(r["owed"] for r in rows), "month": timezone.localdate()},
    )


@role_required("admin", "accountant", "director")
def open_student(request, pk):
    student = get_object_or_404(Student, pk=pk)
    applicant = Applicant.objects.filter(name=student.name).first()
    if applicant:
        return redirect("applicant", pk=applicant.pk)
    messages.error(request, _("No enrolment record is linked to %(name)s.") % {"name": student.name})
    return redirect("debtors")


@role_required("admin", "accountant", "director")
def pay(request):
    post = request.POST
    student = Student.objects.filter(pk=post.get("student") or request.GET.get("student") or 0).first()
    receipt, error = None, ""
    if request.method == "POST" and student:
        try:
            amount = int(post["amount"])
            day = dt.date.fromisoformat(post["date"])
        except (ValueError, KeyError):
            amount = 0
        if amount <= 0 or post.get("method") not in PAYMENT_METHODS:
            error = _("Enter a positive amount and a payment method.")
        else:
            month = dt.date.fromisoformat(post["month"] + "-01") if post.get("month") else day.replace(day=1)
            receipt = Payment.objects.create(
                student=student,
                month=month,
                amount=amount,
                method=post["method"],
                discount=post.get("discount", "None"),
                paid_on=day,
            )
            receipt.issue_receipt()
    info = student.payment_summary() if student else None
    status = info["status"] if info else "Unpaid"
    return render(
        request,
        "pay.html",
        {
            "s": student,
            "info": info,
            "rec": receipt,
            "err": error,
            "students": Student.objects.all(),
            "stat": status,
            "today": timezone.localdate(),
            "methods": ("Cash", "Card", "Payme", "Click"),
            "months": [timezone.localdate().replace(day=1) - dt.timedelta(days=30 * k) for k in (1, 0)] + [
                (timezone.localdate().replace(day=1) + dt.timedelta(days=32)).replace(day=1)],
        },
    )


@role_required("parent", "student", "admin", "accountant", "director")
def receipt(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    role = request.session["role"]
    if role == "parent" and payment.student.parent_id != request.user.id:
        return redirect("home")
    if role == "student" and payment.student.user_id != request.user.id:
        return redirect("home")
    if request.GET.get("dl"):
        date = payment.paid_on or payment.created.date()
        text = (
            "ITmatic Learning Center\n"
            f"{_('Receipt')} {payment.receipt_no}\n"
            f"{_('Student')}: {payment.student}\n"
            f"{_('Amount')}: {payment.amount:,} so‘m\n".replace(",", " ")
            + f"{_('Method')}: {_(payment.method)}\n"
            f"{_('Date')}: {date:%d.%m.%Y}\n"
        )
        response = HttpResponse(text, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f"attachment; filename={payment.receipt_no}.txt"
        return response
    return render(request, "receipt.html", {"p": payment})