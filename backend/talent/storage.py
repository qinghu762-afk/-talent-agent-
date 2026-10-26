import hashlib
import io
import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .config import settings

SUPPORTED = {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".txt"}


@dataclass
class IncomingFile:
    filename: str
    content: bytes
    error: str | None = None


def safe_name(value):
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or ":" in value or "\x00" in value:
        raise UploadRejected("文件名包含不安全路径")
    return path.name[:240]


def expand_uploads(files):
    config = settings()
    output = []
    total = 0

    def append(name, content):
        nonlocal total
        name = safe_name(name)
        if len(output) >= config.max_batch_files:
            raise UploadRejected("每批最多 200 个文件")
        total += len(content)
        if total > config.max_batch_bytes:
            raise UploadRejected("每批解压后总大小不能超过 200MB")
        suffix = Path(name).suffix.lower()
        error = None
        if suffix not in SUPPORTED:
            error = "不支持此文件格式"
        elif not content:
            error = "文件为空"
        elif len(content) > config.max_file_bytes:
            error = "文件超过 20MB"
        elif suffix == ".pdf" and not content.lstrip().startswith(b"%PDF"):
            error = "PDF 文件头无效"
        elif suffix == ".docx":
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as document:
                    members = document.infolist()
                    if "word/document.xml" not in document.namelist():
                        error = "DOCX 缺少文档内容"
                    if len(members) > 10000 or sum(m.file_size for m in members) > 100 * 1024 * 1024:
                        error = "DOCX 解压大小超出限制"
            except zipfile.BadZipFile:
                error = "DOCX 文件损坏"
        output.append(IncomingFile(name, content if not error else b"", error))

    for name, content in files:
        safe_name(name)
        if Path(name).suffix.lower() != ".zip":
            append(name, content)
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = [m for m in archive.infolist() if not m.is_dir()]
                if len(output) + len(members) > config.max_batch_files:
                    raise UploadRejected("压缩包内文件数量超出批次限制")
                if total + sum(m.file_size for m in members) > config.max_batch_bytes:
                    raise UploadRejected("压缩包解压后超过 200MB")
                for member in members:
                    safe_name(member.filename)
                    mode = member.external_attr >> 16
                    if stat.S_ISLNK(mode) or member.flag_bits & 1:
                        raise UploadRejected("不支持符号链接或加密压缩包")
                    if Path(member.filename).suffix.lower() == ".zip":
                        raise UploadRejected("不支持嵌套压缩包")
                    if member.file_size > config.max_file_bytes or member.file_size > max(1, member.compress_size) * 200:
                        raise UploadRejected("压缩包成员超过大小或压缩比例限制")
                    append(member.filename, archive.read(member))
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
            raise UploadRejected("压缩包无法读取") from None
    if not output:
        raise UploadRejected("请选择至少一个文件")
    return output


def persist_file(incoming):
    digest = hashlib.sha256(incoming.content).hexdigest()
    folder = settings().data_dir / "originals" / digest[:2]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (digest + Path(incoming.filename).suffix.lower())
    if not path.exists():
        temporary = folder / (digest + "." + os.urandom(8).hex() + ".part")
        temporary.write_bytes(incoming.content)
        os.replace(temporary, path)
    return digest, str(path)


class UploadRejected(ValueError):
    pass

