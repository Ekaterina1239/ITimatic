from django import forms
from .models import Applicant, Group, Lesson, Payment, Student
from .scheduling import room_clash, teacher_clash


class ApplicantForm(forms.ModelForm):
    class Meta:
        model = Applicant
        fields = ["name", "age", "phone", "parent_name", "parent_phone", "course", "kind"]


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name", "course", "level", "kind", "teacher", "room", "monthly_fee"]


class LessonForm(forms.ModelForm):
    start = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
                                input_formats=["%Y-%m-%dT%H:%M"])

    class Meta:
        model = Lesson
        fields = ["group", "start", "duration", "room", "is_makeup"]

    def clean(self):
        d = super().clean()
        g, start, dur = d.get("group"), d.get("start"), d.get("duration")
        if g and start and dur:
            tmp = Lesson(group=g, start=start, duration=dur)
            room = d.get("room") or g.room
            d["room"] = room
            c = room_clash(room, start, tmp.end)
            if c:
                raise forms.ValidationError(f"Room {room} is busy: {c[0]}")
            if g.teacher and teacher_clash(g.teacher, start, tmp.end):
                raise forms.ValidationError("The teacher already has a lesson at this time")
        return d


class PaymentForm(forms.Form):
    student = forms.ModelChoiceField(Student.objects.filter(active=True))
    amount = forms.IntegerField(min_value=1, label="Amount (so'm)")
    method = forms.ChoiceField(choices=Payment.METHODS)
    reference = forms.CharField(required=False, max_length=80, label="Transaction no. (Payme / Click / card)")
