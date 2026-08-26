from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class RegistrationForm(UserCreationForm):
    """
    Extends Django's built-in UserCreationForm (secure password handling,
    validation, hashing — all handled by Django) with email and phone.
    Location is intentionally NOT collected here — it's set up in Phase 3
    as part of Solar System Setup.
    """
    email = forms.EmailField(required=True)
    phone = forms.CharField(max_length=15, required=False)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            # Profile already exists via the post_save signal — just fill in phone.
            user.profile.phone = self.cleaned_data.get('phone', '')
            user.profile.save()
            user.email = self.cleaned_data['email']
            user.save()
        return user