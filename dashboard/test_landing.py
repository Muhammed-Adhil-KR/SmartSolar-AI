from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from dashboard.views import CONTACT

User = get_user_model()


class LandingPageTests(TestCase):
    def test_urls(self):
        self.assertEqual(reverse('dashboard:landing'), '/')
        self.assertEqual(reverse('dashboard:home'), '/dashboard/')

    def test_public_page_for_visitors(self):
        r = self.client.get(reverse('dashboard:landing'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Get started')
        self.assertContains(r, 'How it works')
        self.assertContains(r, 'all figures in SmartSolar are estimates')
        self.assertNotContains(r, 'Open dashboard')

    def test_logged_in_user_sees_open_dashboard(self):
        User.objects.create_user('sunny', password='pw12345!x')
        self.client.login(username='sunny', password='pw12345!x')
        r = self.client.get(reverse('dashboard:landing'))
        self.assertContains(r, 'Open dashboard')
        self.assertNotContains(r, 'Get started')

    def test_contact_details_are_shown(self):
        r = self.client.get(reverse('dashboard:landing'))
        self.assertContains(r, CONTACT['name'])
        self.assertContains(r, CONTACT['email'])

    def test_dashboard_still_requires_login(self):
        r = self.client.get(reverse('dashboard:home'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r.url)