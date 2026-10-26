"""Isolated, local-only MinerU adapter; no library, external parsing, or VLM."""
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

from fastapi import FastAPI, File, HTTPException, UploadFile
from mineru.parser import parse

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
parse_lock = Lock()
MAX_BYTES = 50 * 1024 * 1024
ALLOWED = {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


@app.get("/health")
def health():
    return {"status": "ok", "parser_version": f"mineru-{version('mineru')}"}


def parse_document(path: Path) -> tuple[str, str]:
    if path.suffix in {".doc", ".docx"}:
        return parse(path, tier="flash", image_analysis=False).markdown(), "flash-native"
    if path.suffix == ".pdf":
        # Inspect every page, so a text cover cannot hide scanned resume pages.
        import pypdfium2 as pdfium

        with pdfium.PdfDocument(str(path)) as document:
            needs_ocr = False
            for page in document:
                try:
                    text_page = page.get_textpage()
                    try:
                        if sum(c.isalnum() for c in text_page.get_text_range()) < 20:
                            needs_ocr = True
                    finally:
                        text_page.close()
                finally:
                    page.close()
        if not needs_ocr:
            native = parse(path, tier="flash", ocr_mode="txt", image_analysis=False).markdown()
            if sum(character.isalnum() for character in native) >= 80:
                return native, "flash-native"
    return parse(path, tier="basic", ocr_mode="ocr", image_analysis=False).markdown(), "basic-onnx-cpu"


@app.post("/parse")
def parse_file(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(415, "不支持的文件格式")
    try:
        with TemporaryDirectory(prefix="talent-parse-") as temporary:
            path = Path(temporary) / f"input{suffix}"
            total = 0
            with path.open("wb") as target:
                while chunk := file.file.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise HTTPException(413, "文件超过 50MB")
                    target.write(chunk)
            if total == 0:
                raise HTTPException(422, "文件为空")
            with parse_lock:
                text, tier = parse_document(path)
            if not text.strip():
                raise HTTPException(422, "未解析到可读文字")
            return {"text": text, "parser_version": f"mineru-{version('mineru')}/{tier}"}
    except HTTPException:
        raise
    except Exception as error:
        # Original files, text, and internal paths must not enter API error responses.
        raise HTTPException(422, f"本地解析失败：{type(error).__name__}") from error
    finally:
        file.file.close()
