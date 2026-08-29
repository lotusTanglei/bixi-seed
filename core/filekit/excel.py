import re
from datetime import date, datetime, time
from pathlib import Path
from zipfile import BadZipFile

from django.conf import settings
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


EXCEL_EXTENSIONS = frozenset({".xlsx", ".xlsm"})


class ExcelParseError(ValueError):
    """Excel 文件格式或内容超过解析边界时抛出的异常。"""


def _source_name(source):
    return Path(str(getattr(source, "name", source))).name


def _is_empty(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _trim_empty_tail(values):
    values = list(values)
    while values and _is_empty(values[-1]):
        values.pop()
    return values


def _cell_value(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def _column_names(header):
    names = []
    used = set()
    for index, value in enumerate(header, start=1):
        base = re.sub(r"\s+", "_", str(value).strip()) if not _is_empty(value) else f"column_{index}"
        base = base[:120] or f"column_{index}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base[:116]}_{suffix}"
            suffix += 1
        names.append(candidate)
        used.add(candidate)
    return names


def parse_excel_upload(source, *, sheet_name=None, max_rows=None, max_columns=None):
    """读取 Excel 首行表头并返回 JSON 友好的行数据，不执行公式或宏。"""

    source_name = _source_name(source)
    suffix = Path(source_name).suffix.lower()
    if suffix not in EXCEL_EXTENSIONS:
        raise ExcelParseError("当前只支持 .xlsx 和 .xlsm 文件")

    size = getattr(source, "size", None)
    if size is not None and size > settings.BIXI_UPLOAD_MAX_BYTES:
        raise ExcelParseError(f"Excel 文件不能超过 {settings.BIXI_UPLOAD_MAX_BYTES} 字节")
    row_limit = max_rows if max_rows is not None else settings.BIXI_EXCEL_MAX_ROWS
    column_limit = max_columns if max_columns is not None else settings.BIXI_EXCEL_MAX_COLUMNS

    try:
        workbook = load_workbook(source, read_only=True, data_only=True, keep_links=False)
    except (BadZipFile, InvalidFileException, KeyError, OSError, ValueError, TypeError) as exc:
        raise ExcelParseError("Excel 文件无法读取，请确认文件没有损坏") from exc

    try:
        if not workbook.sheetnames:
            raise ExcelParseError("Excel 文件没有工作表")
        if sheet_name is None:
            worksheet = workbook.active
        elif sheet_name in workbook.sheetnames:
            worksheet = workbook[sheet_name]
        else:
            raise ExcelParseError(f"找不到工作表: {sheet_name}")

        header = None
        rows = []
        for values in worksheet.iter_rows(values_only=True):
            values = _trim_empty_tail(values)
            if header is None:
                if not values:
                    continue
                if len(values) > column_limit:
                    raise ExcelParseError(f"Excel 列数不能超过 {column_limit}")
                header = _column_names(values)
                continue
            if not values:
                continue
            if len(values) > column_limit or len(values) > len(header):
                raise ExcelParseError("Excel 数据列数超过表头列数或允许上限")
            if len(rows) >= row_limit:
                raise ExcelParseError(f"Excel 数据行数不能超过 {row_limit}")
            padded = values + [None] * (len(header) - len(values))
            rows.append({column: _cell_value(padded[index]) for index, column in enumerate(header)})

        if header is None:
            raise ExcelParseError("Excel 没有可用的表头")
        return {
            "file_name": source_name,
            "sheet_name": worksheet.title,
            "columns": header,
            "rows": rows,
            "row_count": len(rows),
        }
    finally:
        workbook.close()
