import csv
from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from . import finance
from .forms import PaymentForm
from .models import *
from .notify import notify
from .roles import role, role_required

MONEY = ("admin", "accountant")


@role_required("admin", "accountant")
def students(request):
    q = request.GET.get("q", "").strip()
    qs = Student.objects.filter(active=True).select_related("group", "parent__profile")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(parent__profile__phone__icontains=q.replace("+", "")) | Q(group__name__icontains=q))
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "students.html", {"page": page, "q": q})


@role_required(*MONEY)
def student_finance(request, pk):
    s = get_object_or_404(Student.objects.select_related("group", "parent__profile"), pk=pk)
    fees, credit = finance.ledger(s)
    r = role(request.user)
    return render(request, "student_finance.html", {"s": s, "fees": list(reversed(fees)), "credit": credit,
                  "due": sum(f.due for f in fees), "open_fees": [f for f in fees if f.due > 0],
                  "payments": s.payments.select_related("received_by").order_by("-created_at"),
                  "discounts": s.discountrequest_set.select_related("fee").order_by("-created_at"),
                  "can_edit": r in MONEY,
                  "att": Attendance.objects.filter(student=s).count()})


@role_required(*MONEY)
def payment_new(request):
    form = PaymentForm(request.POST or None, initial={"student": request.GET.get("student")})
    if form.is_valid():
        d = form.cleaned_data
        if d["method"] in ("payme", "click") and not d["reference"]:
            form.add_error("reference", "Required for Payme / Click")
        else:
            p = Payment.objects.create(student=d["student"], amount=d["amount"], method=d["method"],
                                       reference=d["reference"], received_by=request.user)
            due, credit = finance.totals(p.student)
            notify(p.student.parent, "Payment received: {amount}, receipt {no}", amount=finance.som(p.amount), no=p.receipt_no)
            if credit:
                messages.info(request, f"Overpayment: {finance.som(credit)} credit will cover the next month")
            return redirect("receipt", p.pk)
    return render(request, "form.html", {"form": form, "title": "Take payment", "back": "finance"})


@role_required("admin", "accountant", "parent", "student")
def receipt(request, pk):
    p = get_object_or_404(Payment.objects.select_related("student__group", "received_by"), pk=pk)
    r = role(request.user)
    if r == "parent" and p.student.parent_id != request.user.id or r == "student" and p.student.user_id != request.user.id:
        raise PermissionDenied
    due, credit = finance.totals(p.student)
    return render(request, "receipt.html", {"p": p, "due": due, "credit": credit})


@role_required("accountant")
@require_POST
def discount_request(request, pk):
    s = get_object_or_404(Student, pk=pk)
    fee = get_object_or_404(Fee, pk=request.POST.get("fee"), student=s)
    try:
        amount = int(request.POST.get("amount", 0))
    except ValueError:
        amount = 0
    reason = request.POST.get("reason", "").strip()
    if not (0 < amount <= fee.net) or not reason:
        messages.error(request, "Enter an amount (not more than the fee) and a reason")
    else:
        DiscountRequest.objects.create(student=s, fee=fee, amount=amount, reason=reason, requested_by=request.user)
        messages.success(request, "Sent to the administrator for approval")
    return redirect("student_finance", pk)


@role_required("admin", "accountant")
def discounts(request):
    r = role(request.user)
    if request.method == "POST":
        if r != "admin":
            raise PermissionDenied
        with transaction.atomic():
            d = get_object_or_404(DiscountRequest.objects.select_for_update(), pk=request.POST.get("id"), status="pending")
            ok = request.POST.get("decision") == "approve"
            d.status, d.decided_by, d.decided_at = ("approved" if ok else "rejected"), request.user, timezone.now()
            d.save()
            if ok:
                d.fee.discount = min(d.fee.discount + d.amount, d.fee.amount)
                d.fee.save()
        notify(d.requested_by, "Discount approved: {student}, {amount}" if ok else "Discount rejected: {student}, {amount}",
               student=d.student.name, amount=finance.som(d.amount))
        return redirect("discounts")
    return render(request, "discounts.html", {"items": DiscountRequest.objects.select_related("student", "fee", "requested_by").order_by("status", "-created_at")[:100], "can": r == "admin"})


@role_required(*MONEY)
def finance_report(request):
    month = (parse_date((request.GET.get("month") or "") + "-01") or timezone.localdate()).replace(day=1)
    nxt = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    pays = Payment.objects.filter(created_at__date__gte=month, created_at__date__lt=nxt).select_related("student", "received_by")
    if request.GET.get("csv"):
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="payments-{month:%Y-%m}.csv"'
        w = csv.writer(resp)
        w.writerow(["receipt", "date", "student", "amount", "method", "reference", "received_by"])
        for p in pays:
            w.writerow([p.receipt_no, timezone.localtime(p.created_at).strftime("%Y-%m-%d %H:%M"), p.student.name, p.amount,
                        p.method, p.reference, p.received_by.get_username() if p.received_by else ""])
        return resp
    by = [(lbl, pays.filter(method=m).aggregate(s=Sum("amount"))["s"] or 0) for m, lbl in Payment.METHODS]
    charged = Fee.objects.filter(month=month)
    return render(request, "finance.html", {"month": month, "by": by, "total": sum(v for _, v in by), "pays": pays.order_by("-created_at")[:100],
                  "charged": sum(f.net for f in charged), "debt": sum(x["due"] for x in finance.debtors(month)),
                  "pending": DiscountRequest.objects.filter(status="pending").count()})


@role_required("admin", "accountant")
def debtors(request):
    """FR-04: monthly debtors list, per branch. Contact outcome (Promised by / No answer / Leaving) is recorded per student and month."""
    month = (parse_date((request.GET.get("month") or "") + "-01") or timezone.localdate()).replace(day=1)
    branch = None                 # branches are out of the current scope (field kept on Group for later)
    q = request.GET.get("q", "").strip().lower()
    back = f"{request.path}?month={month:%Y-%m}" + (f"&branch={branch.pk}" if branch else "")
    if request.method == "POST":
        s = get_object_or_404(Student, pk=request.POST.get("student"))
        if request.POST.get("remind"):
            due, _ = finance.totals(s, month)
            notify(s.parent, "Payment reminder for {student}: {amount} due", student=s.name, amount=finance.som(due))
            messages.success(request, "Reminder sent")
        else:
            outcome, pb = request.POST.get("outcome"), parse_date(request.POST.get("promised_by", ""))
            if outcome not in dict(DebtorNote.OUTCOMES) or (outcome == "promised" and not pb):
                messages.error(request, "Promised by needs a date")
            else:
                DebtorNote.objects.create(student=s, month=month, outcome=outcome, promised_by=pb if outcome == "promised" else None, created_by=request.user)
        return redirect(back)
    rows = finance.debtors(month, branch)
    if q:
        rows = [r for r in rows if q in r["s"].name.lower() or q in (r["phone"] or "")]
    for r in rows:
        r["note"] = r["s"].debtor_notes.filter(month=month).first()
    return render(request, "debtors.html", {"rows": rows, "month": month, "total": sum(r["due"] for r in rows), "q": request.GET.get("q", ""), "outcomes": DebtorNote.OUTCOMES, "can_note": True})
