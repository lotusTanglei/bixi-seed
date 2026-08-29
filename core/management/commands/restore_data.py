import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "将通过校验的 SQLite 备份恢复到当前配置的数据库。"

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True)

    def handle(self, *args, **options):
        source = Path(options["input"]).expanduser().resolve()
        target = Path(settings.DATABASES["default"]["NAME"]).resolve()
        if not source.is_file():
            raise CommandError(f"备份文件不存在: {source}")
        if source == target:
            raise CommandError("备份文件不能与当前数据库相同")
        try:
            with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_connection:
                result = source_connection.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise CommandError("备份文件完整性检查失败")
                target.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(target) as target_connection:
                    source_connection.backup(target_connection)
        except sqlite3.DatabaseError as exc:
            raise CommandError(f"无法读取 SQLite 备份: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"数据库恢复完成: {target}"))
