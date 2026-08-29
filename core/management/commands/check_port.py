import socket

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "检查指定地址和端口是否可以监听。"

    def add_arguments(self, parser):
        parser.add_argument("--host", required=True)
        parser.add_argument("--port", required=True, type=int)

    def handle(self, *args, **options):
        host = options["host"]
        port = options["port"]
        if not 1 <= port <= 65535:
            raise CommandError("端口必须在 1 到 65535 之间")
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)
        checked = set()
        try:
            for family, socket_type, protocol, _, address in addresses:
                key = (family, address)
                if key in checked:
                    continue
                checked.add(key)
                with socket.socket(family, socket_type, protocol) as listener:
                    listener.bind(address)
        except OSError as exc:
            raise CommandError(f"端口 {host}:{port} 不可用，可能已被其他进程占用: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"端口 {host}:{port} 可用。"))
