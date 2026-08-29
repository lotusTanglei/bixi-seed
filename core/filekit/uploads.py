import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from django.conf import settings


class UploadError(ValueError):
    """文件不符合上传边界时抛出的异常。"""


@dataclass(frozen=True)
class StoredUpload:
    """已保存文件的非数据库描述，业务模块可以自行持久化这组信息。"""

    id: str
    original_name: str
    relative_path: str
    size: int
    content_type: str

    @property
    def path(self):
        return upload_root() / self.relative_path


def upload_root():
    root = Path(settings.BIXI_UPLOAD_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_original_name(name):
    value = str(name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not value or value in {".", ".."} or len(value) > 255:
        raise UploadError("文件名无效")
    return value


def _safe_category(category):
    value = str(category or "general").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise UploadError("文件分类只能包含英文、数字、下划线和连字符")
    return value


def _normalized_extensions(allowed_extensions):
    if allowed_extensions is None:
        return None
    return {str(item).lower() if str(item).startswith(".") else f".{str(item).lower()}" for item in allowed_extensions}


def store_uploaded_file(uploaded_file, *, category="general", allowed_extensions=None, max_bytes=None):
    """把 Django UploadedFile 保存到 data/uploads，返回可供业务持久化的描述。"""

    original_name = _safe_original_name(getattr(uploaded_file, "name", ""))
    suffix = Path(original_name).suffix.lower()
    extensions = _normalized_extensions(allowed_extensions)
    if extensions is not None and suffix not in extensions:
        allowed = ", ".join(sorted(extensions))
        raise UploadError(f"文件类型不支持，仅允许: {allowed}")

    limit = max_bytes if max_bytes is not None else settings.BIXI_UPLOAD_MAX_BYTES
    size = getattr(uploaded_file, "size", None)
    if size is not None and size > limit:
        raise UploadError(f"文件不能超过 {limit} 字节")

    category_name = _safe_category(category)
    root = upload_root()
    directory = root / category_name
    directory.mkdir(parents=True, exist_ok=True)
    upload_id = uuid4().hex
    target = directory / f"{upload_id}{suffix}"
    written = 0
    try:
        with target.open("xb") as destination:
            for chunk in uploaded_file.chunks():
                written += len(chunk)
                if written > limit:
                    raise UploadError(f"文件不能超过 {limit} 字节")
                destination.write(chunk)
    except UploadError:
        target.unlink(missing_ok=True)
        raise
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise UploadError("文件保存失败") from exc

    return StoredUpload(
        id=upload_id,
        original_name=original_name,
        relative_path=target.relative_to(root).as_posix(),
        size=written,
        content_type=getattr(uploaded_file, "content_type", None) or "application/octet-stream",
    )


def delete_uploaded_file(stored_upload):
    """只允许删除 upload_root 内的文件，避免业务代码传入任意路径。"""

    root = upload_root()
    candidate = (root / stored_upload.relative_path).resolve()
    if root not in candidate.parents:
        raise UploadError("文件路径超出上传目录")
    try:
        candidate.unlink()
    except FileNotFoundError:
        return False
    return True
