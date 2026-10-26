import hashlib
import io
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

ALLOWED = {".pdf", ".doc", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".xlsx", ".xls"}


def validated_files(files, config):
    output = []
    for filename, content in files:
        name = Path(filename.replace("\\", "/")).name
        if len(content) > config.max_file_bytes:
            raise HTTPException(422, "单文件不能超过 20MB")
        if Path(name).suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    for entry in archive.infolist():
                        path = PurePosixPath(entry.filename.replace("\\", "/"))
                        if path.is_absolute() or ".." in path.parts or ":" in str(path) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                            raise HTTPException(422, "ZIP 包含不安全路径")
                        if entry.is_dir():
                            continue
                        if entry.file_size > config.max_file_bytes or entry.compress_size and entry.file_size / entry.compress_size > 200:
                            raise HTTPException(422, "ZIP 解压大小超限")
                        if path.suffix.lower() not in ALLOWED:
                            raise HTTPException(422, "ZIP 包含不支持的文件")
                        output.append((path.name, archive.read(entry)))
                        if len(output) > config.max_batch_files:
                            raise HTTPException(422, "单批最多 200 份")
            except zipfile.BadZipFile:
                raise HTTPException(422, "ZIP 文件损坏")
        elif Path(name).suffix.lower() in ALLOWED:
            output.append((name, content))
        else:
            raise HTTPException(422, "不支持的文件格式")
    if not output or len(output) > config.max_batch_files or sum(len(x[1]) for x in output) > 400 * 1024 * 1024:
        raise HTTPException(422, "批次为空或超过总大小限制")
    return output


def save_file(root, name, content):
    digest = hashlib.sha256(content).hexdigest()
    folder = root / "originals" / digest[:2]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (digest + Path(name).suffix.lower())
    if not path.exists():
        path.write_bytes(content)
    return digest, str(path.resolve())
