
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class LoginErrorTests(TestCase):
    def test_wrong_password_shows_error_message(self):
        get_user_model().objects.create_user('ann', password='right-pass-123')
        resp = self.client.post(reverse('accounts:login'),
                                {'username': 'ann', 'password': 'wrong'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Please enter a correct username and password')