import re


KEY_RE = re.compile(r"^[a-z][a-z0-9-]{1,99}$")
DEPENDENCY_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:[<>=!~].*)?$")
FORBIDDEN_PATTERNS = (
    re.compile(r"\b(?:eval|exec|__import__)\s*\("),
    re.compile(r"\b(?:subprocess|socket|ctypes)\b"),
    re.compile(r"(?:^|\n)\s*(?:import|from)\s+(?:os|sys|pathlib)\b"),
)


def validate_draft(*, key, files, dependencies):
    errors = []
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        errors.append("key 必须是 2 到 100 个字符的小写英文、数字和连字符")
    if not isinstance(files, dict) or not files:
        errors.append("files 必须是非空对象")
        files = {}
    total_size = 0
    for path, content in files.items():
        if not isinstance(path, str) or path.startswith(("/", "\\")) or ".." in path.split("/"):
            errors.append(f"文件路径不安全: {path}")
            continue
        if not isinstance(content, str):
            errors.append(f"文件内容必须是文本: {path}")
            continue
        total_size += len(content.encode("utf-8"))
        if len(path) > 180:
            errors.append(f"文件路径过长: {path}")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(content):
                errors.append(f"静态检查禁止危险调用: {path}")
                break
    if total_size > 100 * 1024:
        errors.append("草稿文件总大小不能超过 100 KiB")
    if not isinstance(dependencies, list) or len(dependencies) > 50 or any(
        not isinstance(item, str) or not DEPENDENCY_RE.fullmatch(item) for item in dependencies
    ):
        errors.append("dependencies 必须是最多 50 项的依赖名称数组")
    return errors


def checks_payload(errors):
    return {
        "passed": not errors,
        "dependency_check": "passed" if not errors else "failed",
        "static_check": "passed" if not errors else "failed",
        "isolation_ready": not errors,
        "errors": errors,
    }
