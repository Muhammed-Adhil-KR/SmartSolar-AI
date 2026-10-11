from django import forms

from .models import Recommendation


class RecommendationFilterForm(forms.Form):
    """Filters for the history page (submitted with GET, all optional)."""
    recommendation_type = forms.ChoiceField(required=False, label="Type")
    priority = forms.ChoiceField(required=False, label="Priority")
    date_from = forms.DateField(required=False, label="From",
                                widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(required=False, label="To",
                              widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, system, **kwargs):
        super().__init__(*args, **kwargs)
        # Only offer types that fit this user's system type (battery / grid gating).
        self.fields['recommendation_type'].choices = [('', 'All types')] + Recommendation.types_for(system)
        self.fields['priority'].choices = [('', 'All priorities')] + Recommendation.PRIORITY_CHOICES
        for name in ('recommendation_type', 'priority'):
            self.fields[name].widget.attrs['class'] = 'form-select'
        for name in ('date_from', 'date_to'):
            self.fields[name].widget.attrs['class'] = 'form-control'

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('date_from'), cleaned.get('date_to')
        if start and end and start > end:
            raise forms.ValidationError("'From' date must be on or before the 'To' date.")
        return cleaned