"""Ledger logic (UC-3): fees are charged, payments are allocated oldest-first.
Partial payment -> fee stays partly due. Overpayment -> credit that settles future fees automatically."""
from django.db.models import Sum
from django.utils import timezone
from .models import Student


def ledger(student):
    fees = list(student.fees.order_by("month"))
    pool = student.payments.aggregate(s=Sum("amount"))["s"] or 0
    for f in fees:
        take = min(f.net, pool)
        f.paid_amount, f.due = take, f.net - take
        pool -= take
    return fees, pool                      # pool = unused credit


def totals(student, upto=None):
    fees, credit = ledger(student)
    return sum(f.due for f in fees if upto is None or f.month <= upto), credit


def debtors(upto, branch=None):
    """FR-04: students with unpaid fees up to `upto`; oldest unpaid month gives the due date and days overdue."""
    qs = Student.objects.filter(active=True).select_related("group", "parent__profile")
    if branch:
        qs = qs.filter(group__branch=branch)
    today, rows = timezone.localdate(), []
    for s in qs:
        fees, _ = ledger(s)
        open_ = [f for f in fees if f.month <= upto and f.due > 0]
        if not open_:
            continue
        last = s.payments.order_by("-created_at").first()
        prof = getattr(s.parent, "profile", None) if s.parent_id else None
        rows.append({"s": s, "due": sum(f.due for f in open_), "due_date": open_[0].month,
                     "overdue": max((today - open_[0].month).days, 0),
                     "last_payment": timezone.localtime(last.created_at).date() if last else None,
                     "phone": prof.phone if prof else ""})
    return sorted(rows, key=lambda r: (-r["overdue"], -r["due"]))


def som(n):
    return f"{int(n):,}".replace(",", " ") + " so'm"
