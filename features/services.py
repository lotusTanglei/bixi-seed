import math
import re
from datetime import date


FIELD_TYPES = {"text", "number", "date", "enum", "boolean"}
FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
FEATURE_KEY_RE = re.compile(r"^[a-z][a-z0-9-]{0,99}$")
MANIFEST_KEYS = {"version", "fields", "list", "form", "detail", "actions", "permissions"}
VIEW_KEYS = {"columns", "search_fields", "fields"}
ACTION_KEYS = {"create", "read", "update", "delete"}
PERMISSION_CODES = {"feature.read", "feature.create", "feature.update", "feature.delete"}


def _is_string_list(value):
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def validate_manifest(manifest):
    errors = []
    if not isinstance(manifest, dict):
        return ["manifest 必须是对象"]
    unknown_keys = set(manifest) - MANIFEST_KEYS
    if unknown_keys:
        errors.append(f"manifest 包含不支持的字段: {', '.join(sorted(unknown_keys))}")
    if manifest.get("version", 1) != 1:
        errors.append("manifest.version 目前只支持 1")
    fields = manifest.get("fields")
    if not isinstance(fields, list) or not fields:
        errors.append("manifest.fields 至少需要一个字段")
        return errors
    if len(fields) > 50:
        errors.append("manifest.fields 最多支持 50 个字段")
    keys = []
    for index, field in enumerate(fields):
        prefix = f"fields[{index}]"
        if not isinstance(field, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        if set(field) - {"key", "label", "type", "required", "options", "max_length", "min", "max"}:
            errors.append(f"{prefix} 包含不支持的字段")
        key = field.get("key")
        label = field.get("label")
        field_type = field.get("type")
        if not isinstance(key, str) or not FIELD_KEY_RE.fullmatch(key):
            errors.append(f"{prefix}.key 必须是小写字母、数字和下划线组成，且以字母开头")
        elif key in keys:
            errors.append(f"字段 key 重复: {key}")
        else:
            keys.append(key)
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            errors.append(f"{prefix}.label 不能为空且不能超过 120 个字符")
        if not isinstance(field_type, str) or field_type not in FIELD_TYPES:
            errors.append(f"{prefix}.type 必须是 {', '.join(sorted(FIELD_TYPES))} 之一")
        if "required" in field and not isinstance(field["required"], bool):
            errors.append(f"{prefix}.required 必须是布尔值")
        if field_type == "enum":
            options = field.get("options")
            if not _is_string_list(options) or len(options) > 100:
                errors.append(f"{prefix}.options 必须是最多 100 项的字符串数组")
        elif "options" in field:
            errors.append(f"{prefix}.options 只能用于 enum 字段")
        if "max_length" in field and (
            not isinstance(field["max_length"], int)
            or isinstance(field["max_length"], bool)
            or not 1 <= field["max_length"] <= 10000
        ):
            errors.append(f"{prefix}.max_length 必须是 1 到 10000 的整数")
        if field_type != "text" and "max_length" in field:
            errors.append(f"{prefix}.max_length 只能用于 text 字段")
        for bound in ("min", "max"):
            if bound in field and (
                not isinstance(field[bound], (int, float)) or isinstance(field[bound], bool)
            ):
                errors.append(f"{prefix}.{bound} 必须是数字")
        if field_type != "number" and ("min" in field or "max" in field):
            errors.append(f"{prefix}.min/max 只能用于 number 字段")
        if "min" in field and "max" in field and field["min"] > field["max"]:
            errors.append(f"{prefix}.min 不能大于 max")

    field_keys = set(keys)
    for view_name in ("list", "form", "detail"):
        view = manifest.get(view_name, {})
        if not isinstance(view, dict):
            errors.append(f"manifest.{view_name} 必须是对象")
            continue
        if set(view) - VIEW_KEYS:
            errors.append(f"manifest.{view_name} 包含不支持的字段")
        for key in ("columns", "search_fields", "fields"):
            if key in view:
                if not _is_string_list(view[key]) or not set(view[key]).issubset(field_keys):
                    errors.append(f"manifest.{view_name}.{key} 必须引用已定义字段")
    actions = manifest.get("actions", {})
    if not isinstance(actions, dict) or set(actions) - ACTION_KEYS or any(
        not isinstance(value, bool) for value in actions.values()
    ):
        errors.append("manifest.actions 必须是 create/read/update/delete 到布尔值的对象")
    permissions = manifest.get("permissions", {})
    if not isinstance(permissions, dict) or set(permissions) - ACTION_KEYS:
        errors.append("manifest.permissions 只能配置 create/read/update/delete")
    elif any(not isinstance(value, str) or value not in PERMISSION_CODES for value in permissions.values()):
        errors.append("manifest.permissions 包含不支持的权限编码")
    return errors


def manifest_fields(manifest):
    return {
        field["key"]: field
        for field in manifest.get("fields", [])
        if isinstance(field, dict) and "key" in field
    }


def feature_action_enabled(feature, action):
    manifest = feature.manifest if isinstance(feature.manifest, dict) else {}
    actions = manifest.get("actions", {})
    return actions.get(action, True) if isinstance(actions, dict) else True


def feature_permission_code(feature, action):
    manifest = feature.manifest if isinstance(feature.manifest, dict) else {}
    permissions = manifest.get("permissions", {})
    return permissions.get(action, f"feature.{action}") if isinstance(permissions, dict) else f"feature.{action}"


def validate_record_data(manifest, data, *, partial=False):
    errors = []
    if not isinstance(data, dict):
        return ["data 必须是对象"]
    fields = manifest_fields(manifest)
    unknown = set(data) - set(fields)
    if unknown:
        errors.append(f"包含未定义字段: {', '.join(sorted(unknown))}")
    for key, field in fields.items():
        if key not in data:
            if not partial and field.get("required"):
                errors.append(f"字段 {field.get('label', key)} 不能为空")
            continue
        value = data[key]
        if value is None:
            if field.get("required") and not partial:
                errors.append(f"字段 {field.get('label', key)} 不能为空")
            continue
        field_type = field.get("type")
        if field_type == "text" and not isinstance(value, str):
            errors.append(f"字段 {field.get('label', key)} 必须是文本")
        elif field_type == "number" and (
            not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
        ):
            errors.append(f"字段 {field.get('label', key)} 必须是数字")
        elif field_type == "date":
            try:
                if not isinstance(value, str):
                    raise ValueError
                date.fromisoformat(value)
            except ValueError:
                errors.append(f"字段 {field.get('label', key)} 必须是 YYYY-MM-DD 日期")
        elif field_type == "enum" and value not in field.get("options", []):
            errors.append(f"字段 {field.get('label', key)} 不在可选项中")
        elif field_type == "boolean" and not isinstance(value, bool):
            errors.append(f"字段 {field.get('label', key)} 必须是布尔值")
        if isinstance(value, str) and field.get("max_length") and len(value) > field["max_length"]:
            errors.append(f"字段 {field.get('label', key)} 超过长度限制")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "min" in field and value < field["min"]:
                errors.append(f"字段 {field.get('label', key)} 不能小于 {field['min']}")
            if "max" in field and value > field["max"]:
                errors.append(f"字段 {field.get('label', key)} 不能大于 {field['max']}")
    return errors
