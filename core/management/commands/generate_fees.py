from datetime import date
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from core import finance
from core.models import Fee, Student
from core.notify import notify


class Command(BaseCommand):
    help = "Run on the 1st of every month (cron): charge monthly fees, send payment reminders, tell the administrators the debtors list is ready (FR-04)."

    def add_arguments(self, p):
        p.add_argument("--month", help="YYYY-MM (default: current month)")

    def handle(self, *a, **o):
        m = date.fromisoformat(o["month"] + "-01") if o.get("month") else timezone.localdate().replace(day=1)
        made = reminded = 0
        for s in Student.objects.filter(active=True).select_related("group__course", "parent"):
            _, new = Fee.objects.get_or_create(student=s, month=m, defaults={"amount": s.group.fee})
            made += new
            due, _ = finance.totals(s, m)
            if due > 0:
                notify(s.parent, "Payment reminder for {student}: {amount} due", student=s.name, amount=finance.som(due))
                reminded += 1
        rows = finance.debtors(m)
        for adm in User.objects.filter(groups__name__in=["admin", "accountant"]).distinct():
            notify(adm, "Debtors list for {month} is ready: {count} students, {amount}", sms=False,
                   month=m.strftime("%B %Y"), count=len(rows), amount=finance.som(sum(r["due"] for r in rows)))
        self.stdout.write(f"{made} fees created, {reminded} reminders sent, {len(rows)} debtors")
