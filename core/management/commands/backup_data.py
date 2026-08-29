import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "创建一致性的 SQLite 数据库备份。"

    def add_arguments(self, parser):
        parser.add_argument("--output", default="")

    def handle(self, *args, **options):
        source = Path(settings.DATABASES["default"]["NAME"])
        if not source.exists():
            self.stderr.write("数据库文件不存在。")
            return
        target = Path(options["output"] or settings.DATA_DIR / "backups" / f"db-{datetime.now():%Y%m%d-%H%M%S}.sqlite3")
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source) as source_connection, sqlite3.connect(target) as target_connection:
            source_connection.backup(target_connection)
        self.stdout.write(self.style.SUCCESS(f"数据库备份完成: {target}"))
