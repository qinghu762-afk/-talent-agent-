import json
import struct
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from talent import acceptance
from talent.db import Base, Talent, Work, make_engine


def test_fixtures_are_thirty_distinct_synthetic_files_with_independent_jobs(tmp_path):
    manifest = acceptance.generate_fixtures(tmp_path / "fixtures")
    assert len(manifest["resumes"]) == 30
    assert len(manifest["jobs"]) == 5
    assert {r["format"] for r in manifest["resumes"]} == {"txt", "docx", "pdf", "png"}
    assert len({r["sha256"] for r in manifest["resumes"]}) == 30
    assert all(r["synthetic"] and "SYNTHETIC" in r["source_text"] for r in manifest["resumes"])
    assert any("合成人才" in r["source_text"] for r in manifest["resumes"])
    assert all(not r["expected"]["phone"] for r in manifest["resumes"])
    assert any(r["expected"]["email"] is None for r in manifest["resumes"])
    assert all(r["expected"]["email"] is None or r["expected"]["email"].endswith("@example.invalid")
               for r in manifest["resumes"])
    assert all(j["expected_eligible"] and j["requirements"]["required_skills"] for j in manifest["jobs"])
    assert json.loads((tmp_path / "fixtures" / "manifest.json").read_text(encoding="utf-8")) == manifest
    assert len(list((tmp_path / "fixtures" / "resumes").iterdir())) == 30


def test_fixture_containers_have_real_documents_and_negative_files(tmp_path):
    manifest = acceptance.generate_fixtures(tmp_path)
    for row in manifest["resumes"]:
        path = tmp_path / row["path"]
        payload = path.read_bytes()
        if row["format"] == "pdf":
            assert payload.startswith(b"%PDF-1.4") and payload.rstrip().endswith(b"%%EOF")
            assert b"xref" in payload and b"/Type /Page" in payload
            if "scanned" in row["features"] or "mixed" in row["features"]:
                assert b"/Subtype /Image" in payload
            if "multipage" in row["features"]:
                assert b"/Count 2" in payload
        elif row["format"] == "png":
            assert payload[:8] == b"\x89PNG\r\n\x1a\n"
            assert struct.unpack(">II", payload[16:24])[0] >= 600
        elif row["format"] == "docx":
            with zipfile.ZipFile(path) as archive:
                ElementTree.fromstring(archive.read("word/document.xml"))
                assert "[Content_Types].xml" in archive.namelist()
    assert {"scanned", "mixed", "multipage", "two-column"} <= {
        feature for row in manifest["resumes"] for feature in row["features"]}
    assert (tmp_path / "negative" / "malformed.pdf").read_bytes() == b"not a PDF"
    with zipfile.ZipFile(tmp_path / "negative" / "mixed-batch.zip") as archive:
        assert "unsupported.exe" in archive.namelist()
        assert any(name.endswith(".txt") for name in archive.namelist())


def test_new_fixture_label_keeps_truth_but_creates_fresh_source_hashes(tmp_path):
    first = acceptance.generate_fixtures(tmp_path / "first")
    second = acceptance.generate_fixtures(tmp_path / "second", label="integration-v2")
    assert [r["expected"] for r in first["resumes"]] == [r["expected"] for r in second["resumes"]]
    assert all("integration-v2" in r["source_text"] for r in second["resumes"])
    assert all(a["sha256"] != b["sha256"] for a, b in zip(first["resumes"], second["resumes"], strict=True))


def test_fixture_truth_includes_text_physically_written_on_additional_pdf_pages(tmp_path):
    manifest = acceptance.generate_fixtures(tmp_path)
    row = next(r for r in manifest["resumes"] if "multipage" in r["features"])
    assert b"SYNTHETIC SUPPLEMENT" in (tmp_path / row["path"]).read_bytes()
    assert "SYNTHETIC SUPPLEMENT" in row["source_text"]


def test_reindex_resets_all_talents_and_interrupted_work_but_keeps_history(monkeypatch):
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)

    @contextmanager
    def local_session():
        with Session(engine) as db, db.begin():
            yield db

    monkeypatch.setattr(acceptance, "session", local_session)
    with local_session() as db:
        db.add_all([Talent(id="active", profile={}, revision=3, indexed_revision=3, index_model="old"),
                    Talent(id="archived", profile={}, revision=4, indexed_revision=4, index_model="old", active=False)])
        for status in ("queued", "dispatched", "running", "retry", "failed", "completed"):
            db.add(Work(id=status, kind="ingest", payload={}, status=status, lease="lease", attempts=2))
    report = acceptance.reindex()
    assert report == {"talents": 2, "index_tasks_queued": 2, "work_recovered": 3}
    with local_session() as db:
        talents = db.scalars(select(Talent)).all()
        assert all(t.indexed_revision == 0 and t.index_model is None for t in talents)
        indexes = db.scalars(select(Work).where(Work.kind == "index")).all()
        assert {(w.subject_id, w.payload["revision"]) for w in indexes} == {("active", 3), ("archived", 4)}
        for status in ("dispatched", "running", "retry"):
            assert db.get(Work, status).status == "queued"
            assert db.get(Work, status).lease is None
            assert db.get(Work, status).attempts == 2
        assert db.get(Work, "failed").status == "failed"
        assert db.get(Work, "completed").status == "completed"
    engine.dispose()


def test_wait_reports_failure_and_timeout_without_treating_retry_as_success():
    with pytest.raises(RuntimeError, match="failed"):
        acceptance.wait_until(lambda: {"status": "failed"}, timeout=1, interval=0)
    with pytest.raises(TimeoutError, match="retry"):
        acceptance.wait_until(lambda: {"status": "retry"}, timeout=0, interval=0)


def test_reindex_forces_same_revision_embedding_and_archived_vector_deletion(monkeypatch):
    from talent import pipeline
    from talent.schemas import TalentProfile

    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)

    @contextmanager
    def local_session():
        with Session(engine) as db, db.begin():
            yield db

    monkeypatch.setattr(acceptance, "session", local_session)
    monkeypatch.setattr(pipeline, "session", local_session)
    with local_session() as db:
        for active in (True, False):
            db.add(Talent(id=str(active), active=active, revision=2, indexed_revision=2, index_model="same",
                          profile=TalentProfile(name="SYNTHETIC", skills=["Python"]).model_dump()))

    class Models:
        embedded = []

        def versions(self):
            return {"embedding": {"digest": "same"}}

        def embed(self, texts):
            self.embedded.extend(texts)
            return [[1.0, 0.0] for _ in texts]

    class Vectors:
        writes = []

        def replace(self, talent, chunks, vectors):
            self.writes.append((talent.id, talent.active, vectors))

        def search(self, vector, limit):
            return []

    models, vectors = Models(), Vectors()
    runner = pipeline.Pipeline(models, object(), lambda digest: vectors)
    acceptance.reindex()
    with local_session() as db:
        payloads = [w.payload for w in db.scalars(select(Work).where(Work.kind == "index"))]
    for payload in payloads:
        runner.index(payload)
    assert models.embedded
    assert next(write for write in vectors.writes if write[0] == "True")[2]
    assert next(write for write in vectors.writes if write[0] == "False")[2] == []
    engine.dispose()


def test_cli_failure_writes_a_failed_report_without_password(tmp_path, monkeypatch, capsys):
    from talent import cli

    def unavailable(*args):
        raise ConnectionError("secret password must not leak")

    monkeypatch.setattr(cli, "verify", unavailable)
    output = tmp_path / "failed.json"
    assert cli.main(["verify", "--fixtures", "unused", "--output", str(output)]) == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert "secret password" not in capsys.readouterr().err


@pytest.mark.parametrize("fail_embedding", [False, True])
def test_benchmark_isolates_collection_and_releases_resources(monkeypatch, fail_embedding):
    import redis
    from talent import adapters, config

    events, collections, rows = [], [], []

    class Lock:
        def acquire(self):
            events.append("locked")
            return True

        def release(self):
            events.append("released")

    class RedisClient:
        def lock(self, name, **kwargs):
            assert name == "talent:gpu"
            return Lock()

        def close(self):
            events.append("redis-closed")

    class Models:
        def versions(self):
            return {"embedding": {"digest": "real-test-adapter"}}

        def embed(self, texts):
            if fail_embedding:
                raise ConnectionError("embedding unavailable")
            return [[1.0, 0.0] for _ in texts]

    class Client:
        def upsert(self, name, data):
            assert name.startswith("bench_")
            rows.extend(data)

        def flush(self, name):
            assert name.startswith("bench_")

        def query(self, name, **kwargs):
            return [{"count(*)": len(rows)}]

        def has_collection(self, name):
            return name in collections

        def drop_collection(self, name):
            collections.remove(name)
            events.append("deleted")

        def close(self):
            events.append("milvus-closed")

    class Store:
        def __init__(self, digest):
            self.collection = "talent_must_never_be_used"
            self.client = Client()

        def ensure(self):
            assert self.collection.startswith("bench_")
            collections.append(self.collection)

        def search(self, vector, limit):
            return [{"entity": {"talent_id": "0"}, "distance": 1.0}]

    def no_gpu(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi unavailable")

    monkeypatch.setattr(redis, "Redis", SimpleNamespace(from_url=lambda *args, **kwargs: RedisClient()))
    monkeypatch.setattr(config, "settings", lambda: SimpleNamespace(redis_url="redis://local"))
    monkeypatch.setattr(adapters, "PrivateModels", Models)
    monkeypatch.setattr(adapters, "VectorStore", Store)
    monkeypatch.setattr(acceptance.subprocess, "run", no_gpu)
    if fail_embedding:
        with pytest.raises(ConnectionError):
            acceptance.benchmark(65, 3)
    else:
        report = acceptance.benchmark(65, 3)
        assert report["profiles"] == report["vectors"] == 65
        assert report["queries"] == 3
        assert report["gpu_peak_used_mib"] is None
    assert not collections
    assert events == ["locked", "deleted", "milvus-closed", "released", "redis-closed"]
