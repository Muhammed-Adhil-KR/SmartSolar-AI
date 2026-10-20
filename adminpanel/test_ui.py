from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class SearchBoxTests(TestCase):
    def setUp(self):
        User.objects.create_superuser('root', 'root@x.com', 'pw')
        self.client.login(username='root', password='pw')

    def test_users_search_has_a_proper_label(self):
        resp = self.client.get(reverse('adminpanel:users'))
        self.assertContains(resp, 'for="id_q">Search</label>')
        self.assertNotContains(resp, 'Q:')

    def test_every_search_box_has_a_placeholder(self):
        for name in ('users', 'systems', 'appliances', 'predictions', 'recommendations'):
            resp = self.client.get(reverse(f'adminpanel:{name}'))
            self.assertContains(resp, 'name="q"', msg_prefix=name)
            self.assertContains(resp, 'placeholder=', msg_prefix=name)