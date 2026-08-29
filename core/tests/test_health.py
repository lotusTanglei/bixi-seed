import socket

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class HealthTest(TestCase):
    def test_health_returns_ok(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_check_port_rejects_an_occupied_port(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaises(CommandError):
                call_command("check_port", host="127.0.0.1", port=port)
