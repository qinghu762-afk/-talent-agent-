"""Adapter contract tests. Fake MinerU only; these do not validate OCR quality."""
import importlib.util
import sys
import types
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException, UploadFile

fake_parser = types.ModuleType("mineru.parser")
fake_parser.parse = Mock()
spec = importlib.util.spec_from_file_location("talent_mineru_adapter", Path(__file__).with_name("app.py"))
adapter = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"mineru": types.ModuleType("mineru"), "mineru.parser": fake_parser}):
    spec.loader.exec_module(adapter)


class Context:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *args):
        pass


class Page:
    def __init__(self, text):
        self.text = text
        self.closed = False

    def get_textpage(self):
        # PdfTextPage has close(), but no context-manager protocol.
        self.text_page = types.SimpleNamespace(get_text_range=lambda: self.text, close=Mock())
        return self.text_page

    def close(self):
        self.closed = True


class AdapterTests(unittest.TestCase):
    def setUp(self):
        adapter.parse.reset_mock()
        adapter.parse.return_value = types.SimpleNamespace(markdown=lambda: "原文证据" * 40)

    def pdf(self, texts):
        pages = [Page(text) for text in texts]
        engine = types.SimpleNamespace(PdfDocument=lambda path: Context(pages))
        return pages, patch.dict(sys.modules, {"pypdfium2": engine})

    def test_mixed_pdf_does_not_lose_scanned_second_page(self):
        pages, engine = self.pdf(["Native resume cover " * 20, ""])
        with engine:
            text, tier = adapter.parse_document(Path("mixed.pdf"))
        self.assertEqual(tier, "basic-onnx-cpu")
        self.assertTrue(text)
        self.assertEqual(adapter.parse.call_args.kwargs["ocr_mode"], "ocr")
        self.assertTrue(all(page.closed for page in pages))
        self.assertTrue(all(page.text_page.close.called for page in pages))

    def test_native_pdf_uses_flash_without_loading_ocr(self):
        _, engine = self.pdf(["Native resume text " * 20])
        with engine:
            _, tier = adapter.parse_document(Path("native.pdf"))
        self.assertEqual(tier, "flash-native")
        self.assertEqual(adapter.parse.call_count, 1)
        self.assertEqual(adapter.parse.call_args.kwargs["tier"], "flash")

    def test_native_office_has_no_pdf_page_range(self):
        adapter.parse_document(Path("resume.doc"))
        self.assertEqual(adapter.parse.call_args.kwargs, {"tier": "flash", "image_analysis": False})

    def test_parse_failure_does_not_disclose_original_or_path(self):
        file = UploadFile(filename="secret.docx", file=BytesIO(b"private original"))
        with patch.object(adapter, "parse_document", side_effect=ValueError("private original /tmp/internal")):
            with self.assertRaises(HTTPException) as caught:
                adapter.parse_file(file)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertNotIn("private", caught.exception.detail)
        self.assertTrue(file.file.closed)

    def test_oversized_upload_is_rejected_and_closed(self):
        file = UploadFile(filename="resume.docx", file=BytesIO(b"123456"))
        with patch.object(adapter, "MAX_BYTES", 5):
            with self.assertRaises(HTTPException) as caught:
                adapter.parse_file(file)
        self.assertEqual(caught.exception.status_code, 413)
        self.assertTrue(file.file.closed)

    def test_success_returns_parser_version_and_text(self):
        file = UploadFile(filename="resume.docx", file=BytesIO(b"native document"))
        with patch.object(adapter, "parse_document", return_value=("可核实原文", "flash-native")):
            with patch.object(adapter, "version", return_value="4.0.12"):
                self.assertEqual(adapter.parse_file(file), {"text": "可核实原文", "parser_version": "mineru-4.0.12/flash-native"})


if __name__ == "__main__":
    unittest.main()
