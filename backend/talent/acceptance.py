"""Real-service acceptance tools. Fixture truth is independent of model extraction."""
import hashlib
import json
import os
import statistics
import struct
import subprocess
import threading
import time
import zipfile
import zlib
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape

import httpx
from sqlalchemy import select

from .db import Talent, Work, session, utcnow
from .repository import enqueue


def reindex():
    """Rebuild the derived index and reclaim work interrupted by a stopped restore."""
    with session() as db:
        recovered = db.scalars(select(Work).where(
            Work.status.in_(["dispatched", "running", "retry"])).with_for_update()).all()
        for work in recovered:
            work.status, work.lease, work.error = "queued", None, None
            work.available_at = work.updated_at = utcnow()
        talents = db.scalars(select(Talent).with_for_update()).all()
        for talent in talents:
            # Include inactive rows: their stale vectors must be deleted too.
            talent.indexed_revision, talent.index_model = 0, None
            enqueue(db, "index", {"talent_id": talent.id, "revision": talent.revision})
        return {"talents": len(talents), "index_tasks_queued": len(talents), "work_recovered": len(recovered)}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# Portable, embedded 5x7 raster font: scanned fixtures contain pixels, no text layer.
_FONT = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@.-:/(),+_", [
    "01110100011000111111100011000110001", "11110100011000111110100011000111110",
    "01111100001000010000100001000001111", "11110100011000110001100011000111110",
    "11111100001000011110100001000011111", "11111100001000011110100001000010000",
    "01111100001000010111100011000101111", "10001100011000111111100011000110001",
    "11111001000010000100001000010011111", "00111000100001000010000101001001100",
    "10001100101010011000101001001010001", "10000100001000010000100001000011111",
    "10001110111010110101100011000110001", "10001110011010110011100011000110001",
    "01110100011000110001100011000101110", "11110100011000111110100001000010000",
    "01110100011000110001101011001001101", "11110100011000111110101001001010001",
    "01111100001000001110000010000111110", "11111001000010000100001000010000100",
    "10001100011000110001100011000101110", "10001100011000110001100010101000100",
    "10001100011000110101101011010101010", "10001100010101000100010101000110001",
    "10001100010101000100001000010000100", "11111000010001000100010001000011111",
    "01110100011001110101110011000101110", "00100011000010000100001000010001110",
    "01110100010000100010001000100011111", "11110000010000101110000010000111110",
    "00010001100101010010111110001000010", "11111100001000011110000010000111110",
    "01110100001000011110100011000101110", "11111000010001000100010000100001000",
    "01110100011000101110100011000101110", "01110100011000101111000010000101110",
    "01110100011011110101101111000001110", "00000000000000000000000000011000110",
    "00000000000000011111000000000000000", "00000001000010000000001000010000000",
    "00001000100001000100010000100010000", "00100010001000010000100000100000100",
    "00100000100000100001000010001000100", "00000000000000000000000000010001000",
    "00000001000010011111001000010000000", "00000000000000000000000000000011111",
], strict=True))


def _raster(text, font_path=None):
    width, height, scale = 1240, 1754, 3
    if font_path:
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new("L", (width, height), 255)
        font = ImageFont.truetype(str(font_path), 28)
        ImageDraw.Draw(image).multiline_text((40, 40), text, font=font, fill=0, spacing=14)
        return width, height, image.tobytes()
    pixels = bytearray(b"\xff") * (width * height)
    for row, line in enumerate(text.upper().splitlines()):
        for column, char in enumerate(line[:64]):
            glyph = _FONT.get(char, "0" * 35)
            for position, bit in enumerate(glyph):
                if bit == "1":
                    left, top = 40 + column * 6 * scale + position % 5 * scale, 40 + row * 12 * scale + position // 5 * scale
                    for dy in range(scale):
                        offset = (top + dy) * width + left
                        pixels[offset:offset + scale] = b"\x00" * scale
    return width, height, bytes(pixels)


def _png(text, font_path=None):
    width, height, pixels = _raster(text, font_path)

    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    scanlines = b"".join(b"\x00" + pixels[y * width:(y + 1) * width] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))


def _docx(text):
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types '
                         'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Override PartName="/word/document.xml" '
                         'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                         '</Types>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                         'Target="word/document.xml"/></Relationships>')
        paragraphs = "".join('<w:p><w:r><w:t xml:space="preserve">' + escape(line) + '</w:t></w:r></w:p>'
                             for line in text.splitlines())
        archive.writestr("word/document.xml", '<?xml version="1.0" encoding="UTF-8"?><w:document '
                         'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                         + paragraphs + '<w:sectPr/></w:body></w:document>')
    return buffer.getvalue()


def _pdf_parts(text, features):
    parts = [text]
    if "multipage" in features or "mixed" in features:
        parts.append("SYNTHETIC SUPPLEMENT\nProject: SYNTHETIC SYSTEM\n" + "\n".join(text.splitlines()[-3:]))
    return parts


def _pdf(text, features, font_path=None):
    objects = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    pages = []
    parts = _pdf_parts(text, features)
    for page_number, part in enumerate(parts):
        resources = b"/Font << /F1 3 0 R >>"
        scanned = "scanned" in features or ("mixed" in features and page_number == 1)
        if scanned:
            width, height, pixels = _raster(part, font_path)
            compressed = zlib.compress(pixels)
            image_id = len(objects) + 1
            objects.append(f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
                           f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode /Length {len(compressed)} >>\nstream\n".encode()
                           + compressed + b"\nendstream")
            resources += f" /XObject << /Im1 {image_id} 0 R >>".encode()
            content = b"q 595 0 0 842 0 0 cm /Im1 Do Q"
        else:
            lines = part.splitlines()
            commands = []
            for i, line in enumerate(lines):
                column, row = (i // 7, i % 7) if "two-column" in features else (0, i)
                escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                commands.append(f"BT /F1 {8 if column else 10} Tf 1 0 0 1 {35 + column * 280} {800 - row * 24} Tm ({escaped}) Tj ET")
            content = "\n".join(commands).encode("ascii")
        content_id = len(objects) + 1
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
        page_id = len(objects) + 1
        objects.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << ".encode()
                       + resources + f" >> /Contents {content_id} 0 R >>".encode())
        pages.append(page_id)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (f"<< /Type /Pages /Count {len(pages)} /Kids [" + " ".join(f"{p} 0 R" for p in pages) + "] >>").encode()
    output, offsets = bytearray(b"%PDF-1.4\n"), [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return bytes(output)


def _eligible(profile, requirements):
    """Small independent fixture oracle; no call to extraction or production scorer."""
    return (set(requirements.get("required_skills", [])) <= set(profile["skills"])
            and (not requirements.get("location") or profile["location"] == requirements["location"])
            and (not requirements.get("min_education") or bool(profile["education"]))
            and profile["experience_months"] >= requirements.get("min_experience_months", 0)
            and set(requirements.get("required_certificates", [])) <= set(profile["certificates"]))


def generate_fixtures(output, label=None, font_path=None):
    if label and (len(label) > 60 or not label.isascii() or "\n" in label or "\r" in label):
        raise ValueError("Fixture label must be a single ASCII line up to 60 characters")
    if font_path and not Path(font_path).is_file():
        raise ValueError("Scan font does not exist")
    root = Path(output)
    # Reject accidental overwrites of earlier evidence or unrelated directories.
    if root.exists() and any(root.iterdir()):
        raise ValueError("Fixture output must be a new or empty directory")
    (root / "resumes").mkdir(parents=True, exist_ok=True)
    (root / "negative").mkdir()
    resumes = []
    groups = [("Python", "PostgreSQL"), ("Java", "Redis"), ("React", "TypeScript"), ("SQL", "Excel"), ("Go", "Docker")]
    for i in range(1, 31):
        fmt = "txt" if i <= 12 else "docx" if i <= 18 else "pdf" if i <= 26 else "png"
        chinese = fmt in {"txt", "docx"} and i % 2 == 0
        name = f"合成人才{i:03}" if chinese else f"SYNTHETIC{i:03}"
        email = None if i % 10 == 0 else f"candidate{i:03}@example.invalid"
        location = None if i % 11 == 0 else "SHANGHAI" if i % 2 else "BEIJING"
        skills = [] if i % 17 == 0 else list(groups[(i - 1) % 5])
        education = [] if i % 13 == 0 else [{"degree": "Bachelor", "school": "SYNTHETIC UNIVERSITY", "major": "Computing"}]
        end = None if i % 7 == 0 else "2024-01"
        experiences = [{"company": "SYNTHETIC LAB", "title": "ENGINEER", "start": "2020-01", "end": end}]
        certs = ["PMP"] if (i - 1) % 5 == 3 else []
        lines = ["SYNTHETIC TEST DATA - NOT A REAL PERSON", ("姓名: " if chinese else "Name: ") + name]
        if label:
            lines.insert(1, "Test batch: " + label)
        if email:
            lines.append("Email: " + email)
        if location:
            lines.append("Location: " + location)
        if skills:
            lines.append("Skills: " + ", ".join(skills))
        if education:
            lines.append("Education: Bachelor, SYNTHETIC UNIVERSITY, Computing")
        lines += ["Company: SYNTHETIC LAB", "Title: ENGINEER", "Start: 2020-01"]
        if end:
            lines.append("End: " + end)
        if i % 6 == 0:
            experiences.append({"company": "SYNTHETIC LAB TWO", "title": "ENGINEER", "start": "2021-01", "end": "2023-01"})
            lines.append("Concurrent work: SYNTHETIC LAB TWO, ENGINEER, 2021-01 to 2023-01")
        if certs:
            lines.append("Certificates: PMP")
        lines.append("Project: SYNTHETIC SYSTEM")
        text = "\n".join(lines) + "\n"
        features = ["missing-fields"] if any((not email, not location, not education, not skills, not end)) else []
        if i % 6 == 0:
            features.append("overlapping-dates")
        if fmt == "pdf":
            features += {19: [], 20: ["multipage"], 21: ["two-column"], 22: ["two-column"],
                         23: ["scanned"], 24: ["scanned"], 25: ["mixed"], 26: ["mixed"]}[i]
        if fmt == "png":
            features.append("scanned")
        payload = text.encode("utf-8") if fmt == "txt" else _docx(text) if fmt == "docx" else _pdf(text, features, font_path) if fmt == "pdf" else _png(text, font_path)
        relative = f"resumes/synthetic-{i:03}.{fmt}"
        (root / relative).write_bytes(payload)
        resumes.append({"id": f"synthetic-{i:03}", "path": relative, "format": fmt, "synthetic": True,
                        "features": features, "source_text": "\n".join(_pdf_parts(text, features)) if fmt == "pdf" else text,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "expected": {"name": name, "email": email, "phone": None, "location": location,
                                     "skills": skills, "education": education, "experiences": experiences,
                                     "experience_months": 48 if end else 0, "certificates": certs}})
    jobs = []
    for i, (skill, preferred) in enumerate(groups):
        requirements = {"required_skills": [skill], "preferred_skills": [preferred], "min_experience_months": 24,
                        "min_education": "Bachelor", "location": "SHANGHAI", "required_certificates": ["PMP"] if i == 3 else []}
        description = (f"SYNTHETIC TEST JOB {i + 1}. Required skill: {skill}. Preferred skill: {preferred}. "
                       "Minimum 24 months experience. Required education: Bachelor. Required location: SHANGHAI."
                       + (" Required certificate: PMP." if i == 3 else ""))
        jobs.append({"id": f"job-{i + 1}", "title": f"SYNTHETIC {skill} ENGINEER", "description": description,
                     "requirements": requirements,
                     "expected_eligible": [r["id"] for r in resumes if _eligible(r["expected"], requirements)]})
    (root / "negative" / "malformed.pdf").write_bytes(b"not a PDF")
    with zipfile.ZipFile(root / "negative" / "mixed-batch.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        first = resumes[0]
        archive.writestr("synthetic-001.txt", (root / first["path"]).read_bytes())
        archive.writestr("unsupported.exe", b"SYNTHETIC UNSUPPORTED DATA, NOT EXECUTABLE")
    manifest = {"schema_version": 1, "synthetic": True, "resumes": resumes, "jobs": jobs,
                "negative": ["negative/malformed.pdf", "negative/mixed-batch.zip"]}
    if label:
        manifest["label"] = label
    if font_path:
        manifest["scan_font_sha256"] = hashlib.sha256(Path(font_path).read_bytes()).hexdigest()
    write_json(root / "manifest.json", manifest)
    write_json(root / "jobs.json", jobs)
    return manifest


def wait_until(fetch, timeout=3600, interval=2):
    deadline = time.monotonic() + timeout
    while True:
        state = fetch()
        status = state.get("status")
        if status == "completed":
            return state
        if status == "failed":
            raise RuntimeError("Acceptance task failed: " + json.dumps(state, ensure_ascii=False))
        if time.monotonic() >= deadline:
            raise TimeoutError("Acceptance timed out, last state: " + json.dumps(state, ensure_ascii=False))
        time.sleep(interval)


def verify(base_url, username, password_env, fixtures, timeout=7200):
    root = Path(fixtures)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("synthetic") or len(manifest["resumes"]) != 30 or len(manifest["jobs"]) != 5:
        raise ValueError("Expected the generated 30-resume / 5-job synthetic manifest")
    password = os.environ.get(password_env)
    if not password:
        raise ValueError("Password environment variable is missing")
    started = time.monotonic()
    with httpx.Client(base_url=base_url.rstrip("/") + "/api/v1/", timeout=120, trust_env=False) as client:
        def api(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        api("POST", "auth/login", json={"username": username, "password": password})
        with ExitStack() as stack:
            files = []
            for row in manifest["resumes"]:
                path = root / row["path"]
                if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                    raise ValueError("Fixture hash mismatch: " + row["path"])
                files.append(("files", (path.name, stack.enter_context(path.open("rb")))))
            batch = api("POST", "batches", files=files)

        def batch_status():
            value = api("GET", "batches/" + batch["id"])
            statuses = [item["status"] for item in value["items"]]
            value["status"] = "failed" if "failed" in statuses else "completed" if statuses and all(s == "completed" for s in statuses) else ",".join(sorted(set(statuses)))
            return value

        batch = wait_until(batch_status, timeout)
        if len(batch["items"]) != 30:
            raise AssertionError("Batch must contain exactly 30 successful resumes")
        by_filename = {item["filename"]: item for item in batch["items"]}
        talent_ids, checks = {}, []
        for row in manifest["resumes"]:
            item = by_filename[Path(row["path"]).name]
            talent_id = item["talent_id"]
            talent_ids[row["id"]] = talent_id

            def indexed():
                value = api("GET", "talents/" + talent_id)
                value["status"] = "completed" if value["indexed_revision"] == value["revision"] and value["index_model"] else "awaiting-index"
                if value["status"] != "completed":
                    tasks = api("GET", "tasks")
                    failed = [t for t in tasks if t["kind"] == "index" and t["subject_id"] == talent_id and t["status"] == "failed"]
                    if failed:
                        value["status"], value["failed_index_tasks"] = "failed", failed
                return value

            talent = wait_until(indexed, timeout)
            profile, expected = talent["profile"], row["expected"]
            for key in ("name", "email", "phone", "location"):
                actual, target = profile.get(key), expected[key]
                if (actual or "").casefold() != (target or "").casefold():
                    raise AssertionError(f"{row['id']} {key}: expected {target!r}, got {actual!r}")
            if set(profile["skills"]) != set(expected["skills"]):
                raise AssertionError(f"{row['id']} extracted skills differ from fixture truth")
            if profile["experience_months"] != expected["experience_months"]:
                raise AssertionError(f"{row['id']} experience months differ (including missing/overlapping dates)")
            if bool(profile["education"]) != bool(expected["education"]):
                raise AssertionError(f"{row['id']} education missingness differs")
            if set(profile["certificates"]) != set(expected["certificates"]):
                raise AssertionError(f"{row['id']} certificates differ")
            source = "".join(row["source_text"].split()).casefold()
            for evidence in profile.get("evidence", {}).values():
                for entry in evidence:
                    if "".join(entry["quote"].split()).casefold() not in source:
                        raise AssertionError(f"{row['id']} quote is absent from fixture source")
            documents = [d for d in talent["documents"] if d["sha256"] == row["sha256"]]
            if not documents or not profile.get("evidence"):
                raise AssertionError("Missing original source or grounded extraction evidence")
            response = client.get("documents/" + documents[0]["id"] + "/file")
            response.raise_for_status()
            if hashlib.sha256(response.content).hexdigest() != row["sha256"]:
                raise AssertionError("Downloaded original differs from uploaded fixture")
            checks.append({"fixture": row["id"], "talent_id": talent_id, "source_sha256": row["sha256"], "indexed": True})
        if len(set(talent_ids.values())) != 30:
            raise AssertionError("Distinct synthetic identities were incorrectly merged")
        job_checks = []
        for job in manifest["jobs"]:
            created = api("POST", "jobs", json={"title": job["title"], "description": job["description"]})

            def job_state():
                return next((value for value in api("GET", "jobs") if value["id"] == created["id"]), {"status": "missing"})

            extracted = wait_until(job_state, timeout)
            from .schemas import JobRequirements
            expected_requirements = JobRequirements.model_validate(job["requirements"]).model_dump(exclude={"evidence"})
            actual_requirements = JobRequirements.model_validate(extracted["requirements"]).model_dump(exclude={"evidence"})
            if actual_requirements != expected_requirements:
                raise AssertionError(f"{job['id']} JD extraction differs: {actual_requirements}")
            run = api("POST", "jobs/" + created["id"] + "/matches")
            matched = wait_until(lambda: api("GET", "matches/" + run["id"]), timeout)
            fixture_set = set(talent_ids.values())
            found = {r["talent_id"] for r in matched["results"] if r["talent_id"] in fixture_set}
            expected_ids = {talent_ids[key] for key in job["expected_eligible"]}
            if found != expected_ids:
                raise AssertionError(f"{job['id']} matching differs: missing={expected_ids - found}, unexpected={found - expected_ids}")
            for result in matched["results"]:
                if not all(c["status"] == "pass" for c in result["score"]["conditions"]):
                    raise AssertionError("Match contains a failed/unknown hard condition")
            job_checks.append({"fixture": job["id"], "job_id": created["id"], "run_id": run["id"], "expected_matches": len(expected_ids)})
        # Exercise real failure isolation, ZIP expansion and source-hash reuse.
        with (root / "negative" / "malformed.pdf").open("rb") as bad, (root / "negative" / "mixed-batch.zip").open("rb") as zipped:
            negative = api("POST", "batches", files=[("files", ("malformed.pdf", bad)), ("files", ("mixed-batch.zip", zipped))])

        def negative_state():
            value = api("GET", "batches/" + negative["id"])
            value["status"] = "completed" if all(i["status"] in {"completed", "failed"} for i in value["items"]) else "pending"
            return value

        negative = wait_until(negative_state, timeout)
        states = {Path(i["filename"]).name: i for i in negative["items"]}
        if (states["malformed.pdf"]["status"] != "failed" or states["unsupported.exe"]["status"] != "failed"
                or states["synthetic-001.txt"]["status"] != "completed" or not states["synthetic-001.txt"]["reused"]):
            raise AssertionError("Negative batch isolation or duplicate reuse failed")
        system = api("GET", "system")
        if not all(service["ok"] for service in system["services"].values()):
            raise AssertionError("Some local dependencies are unavailable")
    return {"status": "passed", "scope": "real API, parser, models, indexing, jobs, matches, originals, ZIP and failure isolation",
            "offline_network_verified": False, "duration_seconds": round(time.monotonic() - started, 3),
            "resumes": checks, "jobs": job_checks, "negative_batch": negative["id"], "system": system}


def benchmark(count=10000, queries=100):
    """Measure actual embeddings and vector search in a disposable Milvus collection."""
    if count < 1 or queries < 1:
        raise ValueError("Count and queries must be positive")
    from redis import Redis

    from .adapters import PrivateModels, VectorStore
    from .config import settings

    config = settings()
    redis = Redis.from_url(config.redis_url, socket_connect_timeout=5, socket_timeout=5)
    lock = redis.lock("talent:gpu", timeout=172800, blocking_timeout=5)
    if not lock.acquire():
        raise RuntimeError("GPU is busy. Stop the worker before running the isolated benchmark")
    stop = threading.Event()
    gpu_samples = []

    def sample_gpu():
        while not stop.is_set():
            try:
                result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                        capture_output=True, text=True, timeout=5, check=True)
                gpu_samples.append(sum(int(line.strip()) for line in result.stdout.splitlines() if line.strip()))
            except (OSError, ValueError, subprocess.SubprocessError):
                return
            stop.wait(1)

    sampler = threading.Thread(target=sample_gpu, daemon=True)
    sampler.start()
    store = None
    started = time.monotonic()
    try:
        models = PrivateModels()
        versions = models.versions()
        store = VectorStore(versions["embedding"]["digest"])
        store.collection = "bench_" + uuid4().hex
        store.ensure()
        embedded_seconds = 0.0
        stored_seconds = 0.0
        probes = []
        for start in range(0, count, 32):
            ids = range(start, min(count, start + 32))
            texts = [f"SYNTHETIC BENCHMARK {i}. Python PostgreSQL Docker engineer. Experience {24 + i % 120} months. Project service {i % 97}." for i in ids]
            before = time.monotonic()
            vectors = models.embed(texts)
            embedded_seconds += time.monotonic() - before
            if len(vectors) != len(texts):
                raise RuntimeError("Embedding service returned an incomplete batch")
            if len(probes) < queries:
                probes.extend(vectors[:queries - len(probes)])
            data = [{"id": str(i), "talent_id": str(i), "revision": 1, "kind": "summary", "active": True,
                     "location": "shanghai", "experience_months": 24 + i % 120, "education_rank": 3,
                     "skills": ["Python", "PostgreSQL", "Docker"], "certificates": [], "vector": vector}
                    for i, vector in zip(ids, vectors, strict=True)]
            before = time.monotonic()
            store.client.upsert(store.collection, data)
            stored_seconds += time.monotonic() - before
        store.client.flush(store.collection)
        actual_count = int(store.client.query(store.collection, filter="", output_fields=["count(*)"], consistency_level="Strong")[0]["count(*)"])
        if actual_count != count:
            raise AssertionError(f"Expected {count} vectors, found {actual_count}")
        latencies = []
        for i in range(queries):
            before = time.monotonic()
            hits = store.search(probes[i % len(probes)], limit=20)
            latencies.append((time.monotonic() - before) * 1000)
            if not hits:
                raise AssertionError("Vector search returned no benchmark profiles")
        sorted_times = sorted(latencies)
        return {"status": "passed", "synthetic": True, "profiles": actual_count, "vectors": actual_count,
                "vectors_per_profile": 1, "batch_size": 32, "queries": queries, "models": versions,
                "collection": store.collection, "collection_deleted_on_exit": True,
                "embedding_seconds": embedded_seconds, "embedding_profiles_per_second": count / embedded_seconds,
                "upsert_seconds": stored_seconds, "duration_seconds": time.monotonic() - started,
                "search_p50_ms": statistics.median(latencies), "search_p95_ms": sorted_times[max(0, (95 * len(sorted_times) + 99) // 100 - 1)],
                "gpu_peak_used_mib": max(gpu_samples) if gpu_samples else None,
                "gpu_measurement": "sampled total device memory usage; includes other processes" if gpu_samples else "unavailable",
                "scope": "real local embedding and Milvus only; excludes OCR, extraction and full match pipeline"}
    finally:
        stop.set()
        sampler.join(timeout=6)
        try:
            if store is not None:
                try:
                    if store.client.has_collection(store.collection):
                        store.client.drop_collection(store.collection)
                finally:
                    store.client.close()
        finally:
            lock.release()
            redis.close()
