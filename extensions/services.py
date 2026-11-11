"""Static review of inert extension drafts. Never imports or executes draft files."""

import ast
import hashlib
import json
import re
from importlib import metadata
from pathlib import PurePosixPath

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from organizations.models import Permission
from organizations.services import get_membership_permissions


KEY_RE = re.compile(r"^[a-z][a-z0-9-]{1,99}$")
SAFE_STDLIB = {
    "collections", "dataclasses", "datetime", "decimal", "enum", "functools",
    "itertools", "json", "math", "re", "statistics", "typing", "uuid",
}
BLOCKED_IMPORTS = {
    "os", "sys", "pathlib", "subprocess", "socket", "ctypes", "importlib",
    "builtins", "pickle", "marshal", "runpy", "shutil", "threading",
    "multiprocessing", "http", "urllib", "requests", "httpx", "django",
    "rest_framework", "config", "core", "accounts", "organizations", "ai",
    "features", "extensions",
}
BLOCKED_NAMES = {
    "eval", "exec", "compile", "open", "input", "__import__", "globals",
    "locals", "vars", "getattr", "setattr", "delattr", "breakpoint", "__builtins__",
}


def is_utf8_text(value):
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def draft_content_hash(draft):
    payload = {
        "organization": str(draft.organization_id), "key": draft.key, "name": draft.name,
        "description": draft.description, "files": draft.files,
        "dependencies": draft.dependencies, "permission_manifest": draft.permission_manifest,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _dependency_checks(dependencies):
    errors, installed = [], []
    if not isinstance(dependencies, list) or len(dependencies) > 50:
        return ["dependencies 必须是最多 50 项的依赖要求数组"], []
    seen = set()
    for value in dependencies:
        try:
            requirement = Requirement(value) if isinstance(value, str) and len(value) <= 200 else None
        except InvalidRequirement:
            requirement = None
        if requirement is None or requirement.url or requirement.marker or requirement.extras:
            errors.append("依赖必须是已安装包的名称和可选版本约束；不接受 URL、marker 或 extras")
            continue
        name = canonicalize_name(requirement.name)
        if name in seen:
            errors.append(f"重复依赖: {requirement.name}")
            continue
        seen.add(name)
        try:
            version = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            errors.append(f"依赖未安装: {requirement.name}")
            continue
        if requirement.specifier and not requirement.specifier.contains(version, prereleases=True):
            errors.append(f"依赖版本不匹配: {requirement.name} {version} 不满足 {requirement.specifier}")
            continue
        installed.append({"name": name, "version": version, "requirement": value})
    return errors, installed


def _file_checks(files, installed):
    errors = []
    if not isinstance(files, dict) or not files or len(files) > 50:
        return ["files 必须是包含 1 到 50 个文件的对象"]
    total_size = 0
    local_modules = {path.split("/")[0].removesuffix(".py") for path in files if isinstance(path, str) and path}
    installed_names = {item["name"] for item in installed}
    distribution_modules = metadata.packages_distributions() if installed_names else {}
    allowed_external = {module for module, distributions in distribution_modules.items() if any(canonicalize_name(name) in installed_names for name in distributions)}
    for path, content in files.items():
        if (not is_utf8_text(path) or not path or len(path) > 180 or "\\" in path or ":" in path
                or path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/"))
                or any(ord(character) < 32 for character in path)):
            errors.append("文件路径不安全；必须是有效 UTF-8 相对路径")
            continue
        suffix = PurePosixPath(path).suffix.lower()
        if suffix not in {".py", ".json", ".md", ".txt"}:
            errors.append(f"仅支持静态审查 Python、JSON 和说明文本: {path}")
        if not isinstance(content, str):
            errors.append(f"文件内容必须是文本: {path}")
            continue
        try:
            total_size += len(content.encode("utf-8"))
        except UnicodeEncodeError:
            errors.append(f"文件内容必须是有效 UTF-8 文本: {path}")
            continue
        if total_size > 100 * 1024:
            continue
        if suffix == ".json":
            try:
                json.loads(content)
            except (ValueError, RecursionError):
                errors.append(f"JSON 语法错误: {path}")
        if suffix != ".py":
            continue
        try:
            tree = ast.parse(content, filename=path)
        except (SyntaxError, ValueError, RecursionError):
            errors.append(f"Python 语法错误: {path}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in BLOCKED_NAMES:
                errors.append(f"静态检查禁止危险名称 {node.id}: {path}:{node.lineno}")
            elif isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in BLOCKED_NAMES | BLOCKED_IMPORTS | {"system", "popen"}):
                errors.append(f"静态检查禁止危险或私有/反射属性: {path}:{node.lineno}")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if any(alias.name.startswith("_") or any(part in BLOCKED_NAMES | BLOCKED_IMPORTS for part in alias.name.split(".")) for alias in node.names):
                    errors.append(f"静态检查禁止导入危险或私有/反射名称: {path}:{node.lineno}")
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for module in modules:
                    root = module.split(".")[0]
                    if isinstance(node, ast.ImportFrom) and node.level:
                        errors.append(f"静态检查不接受相对导入: {path}:{node.lineno}")
                    elif any(part in BLOCKED_IMPORTS for part in module.split(".")) or root not in SAFE_STDLIB | local_modules | allowed_external:
                        errors.append(f"静态检查禁止或未声明导入 {root}: {path}:{node.lineno}")
    if total_size > 100 * 1024:
        errors.append("草稿文件总大小不能超过 100 KiB")
    return list(dict.fromkeys(errors))


def inspect_draft(*, key, files, dependencies, permission_manifest, membership):
    dependency_errors, installed = _dependency_checks(dependencies)
    static_errors = _file_checks(files, installed)
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        static_errors.insert(0, "key 必须是 2 到 100 个字符的小写英文、数字和连字符")
    permission_errors = []
    if not isinstance(permission_manifest, list) or len(permission_manifest) > 50 or any(not is_utf8_text(code) or len(code) > 120 for code in permission_manifest):
        permission_errors.append("permission_manifest 必须是最多 50 项的权限编码数组")
    elif len(set(permission_manifest)) != len(permission_manifest):
        permission_errors.append("权限清单不能重复")
    else:
        known = set(Permission.objects.filter(code__in=permission_manifest).values_list("code", flat=True))
        allowed = set(get_membership_permissions(membership))
        for code in permission_manifest:
            if code not in known:
                permission_errors.append(f"未知权限: {code}")
            elif code not in allowed:
                permission_errors.append(f"超出当前用户在本组织的权限: {code}")
    errors = dependency_errors + static_errors + permission_errors
    return {
        "passed": not errors,
        "dependency_check": "failed" if dependency_errors else "passed",
        "static_check": "failed" if static_errors else "passed",
        "permission_check": "failed" if permission_errors else "passed",
        "installed_dependencies": installed,
        "execution_status": "not_loaded_or_executed",
        "isolation_evidence": "not_provided",
        "errors": errors,
    }
