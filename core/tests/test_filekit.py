from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from openpyxl import Workbook

from core.filekit import ExcelParseError, UploadError, parse_excel_upload, store_uploaded_file


def make_excel_upload(name="customers.xlsx"):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "客户"
    worksheet.append(["姓名", "联系方式", "日期"])
    worksheet.append(["张三", "13800000000", "2026-08-27"])
    worksheet.append(["李四", "微信 lisi", None])
    output = BytesIO()
    workbook.save(output)
    return SimpleUploadedFile(
        name,
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


class FileKitTest(SimpleTestCase):
    def test_excel_parser_returns_headers_and_json_friendly_rows(self):
        payload = parse_excel_upload(make_excel_upload())

        self.assertEqual(payload["sheet_name"], "客户")
        self.assertEqual(payload["columns"], ["姓名", "联系方式", "日期"])
        self.assertEqual(payload["rows"][0]["姓名"], "张三")
        self.assertEqual(payload["row_count"], 2)

    def test_excel_parser_rejects_unsupported_extension(self):
        with self.assertRaises(ExcelParseError):
            parse_excel_upload(SimpleUploadedFile("customers.xls", b"not supported"))

    def test_upload_storage_uses_generated_name_and_rejects_path_traversal_category(self):
        with TemporaryDirectory() as directory, override_settings(BIXI_UPLOAD_ROOT=directory):
            stored = store_uploaded_file(make_excel_upload("../customers.xlsx"), category="imports", allowed_extensions={".xlsx"})
            self.assertEqual(stored.original_name, "customers.xlsx")
            self.assertTrue(stored.path.exists())
            self.assertNotIn("customers.xlsx", stored.relative_path)
            with self.assertRaises(UploadError):
                store_uploaded_file(make_excel_upload(), category="../imports")

    def test_excel_parser_enforces_row_limit(self):
        with self.assertRaises(ExcelParseError):
            parse_excel_upload(make_excel_upload(), max_rows=1)

    def test_upload_storage_enforces_extension_size_and_category(self):
        with TemporaryDirectory() as directory, override_settings(BIXI_UPLOAD_ROOT=directory):
            with self.assertRaises(UploadError):
                store_uploaded_file(SimpleUploadedFile("notes.txt", b"text"), allowed_extensions={".xlsx"})
            with self.assertRaises(UploadError):
                store_uploaded_file(SimpleUploadedFile("notes.txt", b"12345"), max_bytes=4)
            with self.assertRaises(UploadError):
                store_uploaded_file(SimpleUploadedFile("notes.txt", b"text"), category="bad/category")
