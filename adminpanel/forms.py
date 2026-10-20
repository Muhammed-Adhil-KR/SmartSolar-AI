from django import forms

from decision_support.models import Recommendation
from solar.models import Appliance, SolarSystem


class UserFilterForm(forms.Form):
    STATUS_CHOICES = [('', 'All'), ('active', 'Active'), ('inactive', 'Inactive')]
    q = forms.CharField(required=False, max_length=100,
                        widget=forms.TextInput(attrs={'placeholder': 'Search username, name or email'}))
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False)


class ApplianceFilterForm(forms.Form):
    STATUS_CHOICES = [('', 'All'), ('active', 'Active'), ('inactive', 'Inactive')]
    PRIORITY_CHOICES = [('', 'All priorities')] + list(Appliance.PRIORITY_CHOICES)

    q = forms.CharField(required=False, max_length=100)
    priority = forms.ChoiceField(choices=PRIORITY_CHOICES, required=False)
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False)
    user = forms.IntegerField(required=False, min_value=1)


class SystemFilterForm(forms.Form):
    TYPE_CHOICES = [('', 'All types')] + list(SolarSystem.SYSTEM_TYPE_CHOICES)

    q = forms.CharField(required=False, max_length=100)
    system_type = forms.ChoiceField(choices=TYPE_CHOICES, required=False)


class PredictionFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=100)
    date_from = forms.DateField(required=False)
    date_to = forms.DateField(required=False)
    user = forms.IntegerField(required=False, min_value=1)


class AdminRecommendationFilterForm(forms.Form):
    TYPE_CHOICES = [('', 'All types')] + list(Recommendation.TYPE_CHOICES)
    PRIORITY_CHOICES = [('', 'All priorities')] + list(Recommendation.PRIORITY_CHOICES)

    q = forms.CharField(required=False, max_length=100)
    recommendation_type = forms.ChoiceField(choices=TYPE_CHOICES, required=False)
    priority = forms.ChoiceField(choices=PRIORITY_CHOICES, required=False)
    date_from = forms.DateField(required=False)      # these two filter on the day the advice is FOR
    date_to = forms.DateField(required=False)
    user = forms.IntegerField(required=False, min_value=1)