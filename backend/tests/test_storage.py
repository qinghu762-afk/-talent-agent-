import io
import zipfile

import pytest
from talent.storage import UploadRejected, expand_uploads


def zip_bytes(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, content in entries:
            z.writestr(name, content)
    return out.getvalue()


def test_zip_traversal_is_rejected():
    with pytest.raises(UploadRejected):
        expand_uploads([("x.zip", zip_bytes([("../resume.txt", "hello")]))])


def test_nested_archives_are_rejected():
    with pytest.raises(UploadRejected):
        expand_uploads([("x.zip", zip_bytes([("inner.zip", "fake")]))])


def test_batch_count_limit_counts_unpacked_files():
    with pytest.raises(UploadRejected):
        expand_uploads([("x.zip", zip_bytes([(f"{i}.txt", "hello") for i in range(201)]))])


def test_invalid_member_does_not_hide_valid_file():
    files = expand_uploads([("a.txt", b"hello"), ("bad.exe", b"bad")])
    assert files[0].content == b"hello"
    assert files[1].error


def test_compressed_bomb_rejected_before_reading():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("huge.txt", b"x" * (21 * 1024 * 1024))
    with pytest.raises(UploadRejected):
        expand_uploads([("x.zip", out.getvalue())])

