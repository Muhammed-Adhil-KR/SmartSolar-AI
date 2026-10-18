"""
Test runner that keeps the suite fast and offline. Enable it in settings.py:

    TEST_RUNNER = 'config.test_runner.OfflineTestRunner'

What it changes (tests only, never the running site):
  * Every real HTTP request made through `requests` is blocked and fails at once
    with a ConnectionError, so no test can slowly (or accidentally) call the
    weather, sunlight or geocoding services. Code that handles those failures
    (the dashboard, the solar window) simply falls back, exactly as it would
    when the user is offline. A test that needs data patches the call itself.
    The "weather request failed" warnings this causes are hidden to keep the
    output readable (assertLogs in a test still sees them).
  * Passwords are hashed with a fast hasher. Django's real hashers are slow on
    purpose, and almost every test creates and logs in a user.
"""
import logging
from unittest import mock

import requests
from django.test import override_settings
from django.test.runner import DiscoverRunner


def _blocked(*args, **kwargs):
    raise requests.ConnectionError("Network access is disabled while running tests.")


class OfflineTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._offline_patch = mock.patch.object(requests.sessions.Session, 'request', _blocked)
        self._offline_patch.start()
        self._fast_hasher = override_settings(
            PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
        self._fast_hasher.enable()
        self._quiet = [(name, logging.getLogger(name).level)
                       for name in ('forecast.services', 'forecast.solar_window')]
        for name, _ in self._quiet:
            logging.getLogger(name).setLevel(logging.ERROR)

    def teardown_test_environment(self, **kwargs):
        for name, level in self._quiet:
            logging.getLogger(name).setLevel(level)
        self._fast_hasher.disable()
        self._offline_patch.stop()
        super().teardown_test_environment(**kwargs)