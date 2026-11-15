"""Enrolment pipeline (FR-01): enquiries and the applicant card."""

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from ..models import Applicant, Branch, ContractStatus, EnrolmentStage, Group, LostReason
from .common import role_required

LOST_REASONS = LostReason.values
STAGES = EnrolmentStage.values
# trial step: form field -> (TrialLesson attribute, stage reached)
TRIAL_FIELDS = {
    "conv": ("conversation", EnrolmentStage.GROUP_MATCHING),
    "trial": ("attendance", EnrolmentStage.TRIAL_COMPLETED),
    "feedback": ("feedback", EnrolmentStage.AGREEMENT),
}


NEXT_STEP = {
    "Enquiry": "Book a level test",
    "Assessment": "Placement assessment",
    "Group matching": "Find a suitable group",
    "Trial booked": "Run the free trial",
    "Trial completed": "Review trial feedback",
    "Agreement": "Send parent agreement",
    "Confirmed": "Joined the group",
    "Lost": "Closed",
}
PIPELINE = ["Enquiry", "Assessment", "Group matching", "Trial booked", "Trial completed", "Agreement", "Confirmed"]


def recommended_group(a):
    groups = Group.objects.filter(active=True, branch=a.branch).select_related("teacher")
    match = [g for g in groups if g.course == a.subject and (not a.level or g.level == a.level) and g.has_place()]
    return match[0] if match else next((g for g in groups if g.course == a.subject and g.has_place()), None)


def history(a):
    test, trial, contract = a.steps()
    items = [("Enquiry received", f"{a.parent_name or a.name} · {a.subject}")]
    if test.score is not None:
        items.append(("Knowledge assessment", f"{a.level or test.recommended_level} · {test.score} / 100"))
    elif test.skip_reason:
        items.append(("Level test skipped", test.skip_reason))
    if trial.conversation:
        items.append(("Teacher conversation", trial.conversation))
    if trial.attendance:
        items.append(("Free trial", trial.attendance))
    if trial.feedback:
        items.append(("Student feedback", trial.feedback))
    if contract.is_complete():
        items.append(("Signed contract recorded", contract.number))
    if a.waiting:
        items.append(("Waiting list", "Family will be notified when a place opens"))
    if a.stage == "Lost":
        items.append(("Closed as Lost", a.lost_reason))
    return items


@role_required("admin")
def enrolment(request):
    post = request.POST
    if request.method == "POST":
        if not post.get("name") or not post.get("phone"):
            messages.error(request, _("Name and phone are required."))
            return redirect("enrolment")
        applicant = Applicant.objects.create(
            name=post["name"], phone=post["phone"], parent_name=post.get("parent", ""),
            subject=post.get("subject", ""), level="", branch=Branch.objects.first(), assigned=request.user,
        )
        return redirect("applicant", pk=applicant.pk)
    query, stage, tab = request.GET.get("q", ""), request.GET.get("stage", ""), request.GET.get("tab", "all")
    everyone = Applicant.objects.select_related("assigned")
    applicants = everyone
    if query:
        applicants = applicants.filter(Q(name__icontains=query) | Q(phone__icontains=query) | Q(parent_name__icontains=query))
    if stage:
        applicants = applicants.filter(stage=stage)
    if tab == "action":
        applicants = applicants.exclude(stage__in=["Confirmed", "Lost"])
    elif tab == "confirmed":
        applicants = applicants.filter(stage="Confirmed")
    selected = everyone.filter(pk=request.GET.get("sel")).first() or applicants.first()
    counts = [(s, everyone.filter(stage=s).count()) for s in PIPELINE]
    return render(
        request,
        "enrolment.html",
        {
            "apps": [(a, NEXT_STEP.get(a.stage, "")) for a in applicants], "stages": STAGES, "q": query, "st": stage, "tab": tab,
            "counts": counts, "sel": selected, "total": everyone.count(),
            "in_pipeline": everyone.exclude(stage__in=["Confirmed", "Lost"]).count(),
            "waiting_n": everyone.filter(waiting=True).count(), "declined_n": everyone.filter(stage="Lost").count(),
            "rec": recommended_group(selected) if selected else None,
            "hist": history(selected) if selected else [],
            "next": NEXT_STEP.get(selected.stage, "") if selected else "",
        },
    )


@role_required("admin")
def applicant(request, pk):
    a = get_object_or_404(Applicant, pk=pk)
    if request.method != "POST":
        return render(
            request,
            "applicant.html",
            {
                "a": a,
                "groups": a.branch.active_groups(),
                "reasons": LOST_REASONS,
                "rec": recommended_group(a),
                "hist": history(a),
                "t": a.level_test, "tr": a.trial, "c": a.contract,
            },
        )

    post, act = request.POST, request.POST.get("act")
    if act == "test":
        test = a.level_test
        if post.get("score"):
            test.record(int(post["score"]), post.get("test_date") or None, post.get("rec_level", ""))
            a.stage = EnrolmentStage.ASSESSMENT
        elif post.get("skip_reason"):
            test.skip(post["skip_reason"])
        else:
            messages.error(request, _("Enter a score or a reason for skipping."))
    elif act in TRIAL_FIELDS:
        field, stage = TRIAL_FIELDS[act]
        trial = a.trial
        setattr(trial, field, post["v"])
        trial.save()
        a.stage = stage
    elif act == "prepared":
        a.contract.prepare()
    elif act == "contract":
        if a.contract.record(post.get("no", ""), post.get("date"), request.FILES.get("scan")):
            messages.success(request, _("Signed contract recorded. This applicant can now join a group."))
        else:
            messages.error(request, _("Contract number, signing date and a signed scan are required."))
    elif act == "join":
        group = get_object_or_404(Group, pk=post["group"])
        error = a.join_group(group)
        if error:
            messages.error(request, _(error))
        else:
            messages.success(request, _("Added to %(group)s.") % {"group": group.name})
            return redirect(f"/groups/?g={group.pk}")
    elif act == "wait":
        a.waiting = True
        a.save()
        messages.success(request, _("Added to the waiting list. The family will be contacted when a place opens."))
        return redirect("enrolment")
    elif act == "lost":
        if a.mark_lost(post.get("reason"), post.get("note", "")):
            messages.success(request, _("Application closed as Lost."))
        else:
            messages.error(request, _("A reason is required (details are required for Other)."))
    a.save()
    return redirect("applicant", pk=pk)