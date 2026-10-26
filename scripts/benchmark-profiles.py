"""Real 10k structured-profile/multi-chunk/full-match benchmark in disposable namespaces.

Run inside the API container. No resume extraction/OCR throughput is inferred from this test.
The source PostgreSQL tables and talent_* Milvus collections are never modified.
"""
import json
import os
import statistics
import time
from pathlib import Path
from uuid import uuid4

import httpx
from ollama import ResponseError
from redis import Redis
from sqlalchemy import create_engine, insert, select, text, update
from sqlalchemy.engine import make_url
from talent.config import settings


def main(count=10000, queries=10):
    config = settings()
    namespace = "bench_profiles_" + uuid4().hex
    assert namespace.startswith("bench_profiles_") and namespace[15:].isalnum()
    original_url = config.database_url
    original_engine = create_engine(original_url)
    redis = Redis.from_url(config.redis_url, socket_connect_timeout=5, socket_timeout=5)
    lock = redis.lock("talent:gpu", timeout=7200, blocking_timeout=5)
    if not lock.acquire():
        raise RuntimeError("GPU is busy; stop only the talent worker before benchmarking")
    store, benchmark_engine = None, None
    created = False
    report = {"status": "running", "synthetic": True, "profiles": count, "queries": queries,
              "namespace": namespace, "vectors_per_profile": 4,
              "scope": "real structured PostgreSQL profiles, four chunks each, local embeddings, Milvus and full Pipeline.match; excludes OCR and LLM extraction"}
    started = time.monotonic()
    try:
        with original_engine.begin() as connection:
            connection.execute(text('CREATE SCHEMA "' + namespace + '"'))
        created = True
        isolated = make_url(original_url).update_query_dict({"options": "-csearch_path=" + namespace})
        os.environ["DATABASE_URL"] = isolated.render_as_string(hide_password=False)
        settings.cache_clear()
        from talent import db
        from talent.adapters import PrivateModels, VectorStore, vector_chunks
        from talent.domain import derive_portrait
        from talent.pipeline import Pipeline
        from talent.schemas import Education, Evidence, Experience, JobRequirements, Project, TalentProfile

        benchmark_engine = db.engine()
        db.Base.metadata.create_all(benchmark_engine)
        models = PrivateModels()
        versions = models.versions()
        digest = versions["embedding"]["digest"]
        store = VectorStore(digest)
        store.collection = namespace
        store.ensure()
        embedding_seconds = 0.0
        embedding_retries = 0
        upsert_seconds = 0.0
        vector_count = 0
        for start in range(0, count, 64):
            rows, chunks, records = [], [], []
            for i in range(start, min(count, start + 64)):
                talent_id = str(uuid4())
                description = f"SYNTHETIC {i}: Python PostgreSQL payment service development"
                profile = derive_portrait(TalentProfile(
                    name=f"SYNTHETIC_BENCH_{i:05d}", location="SHANGHAI", skills=["Python", "PostgreSQL", "Docker"],
                    education=[Education(degree="Bachelor")],
                    experiences=[Experience(title="Python engineer", start="2018-01", end="2024-01",
                                            description=description, skills=["Python", "PostgreSQL"])],
                    projects=[Project(name=f"SYNTHETIC service {i}", description=description, skills=["Python"])],
                    evidence={"name": [Evidence(quote=f"SYNTHETIC_BENCH_{i:05d}")],
                              "experiences.0.description": [Evidence(quote=description)],
                              "projects.0.description": [Evidence(quote=description)]}))
                rows.append({"id": talent_id, "name": profile.name, "profile": profile.model_dump(), "revision": 1,
                             "indexed_revision": 0, "active": True})
                parts = vector_chunks(profile)
                assert len(parts) == 4
                for j, chunk in enumerate(parts):
                    chunks.append(chunk["text"])
                    records.append({"id": f"{talent_id}:1:{j}", "talent_id": talent_id, "revision": 1,
                                    "kind": chunk["kind"], "active": True, "location": "shanghai",
                                    "experience_months": 72, "education_rank": 3,
                                    "skills": profile.skills, "certificates": []})
            with db.session() as session:
                session.execute(insert(db.Talent), rows)
            before = time.monotonic()
            for attempt in range(4):
                try:
                    vectors = models.embed(chunks)
                    break
                except (httpx.HTTPError, ResponseError):
                    if attempt == 3:
                        raise
                    embedding_retries += 1
                    print(json.dumps({"embedding_retry": embedding_retries, "profile_offset": start}), flush=True)
                    time.sleep(5 * 2 ** attempt)
            embedding_seconds += time.monotonic() - before
            assert len(vectors) == len(records)
            for row, vector in zip(records, vectors, strict=True):
                row["vector"] = vector
            before = time.monotonic()
            store.client.upsert(store.collection, records)
            upsert_seconds += time.monotonic() - before
            with db.session() as session:
                session.execute(update(db.Talent).where(db.Talent.id.in_([r["id"] for r in rows]))
                                .values(indexed_revision=1, index_model=digest))
            vector_count += len(vectors)
            if start % 1024 == 0:
                print(json.dumps({"indexed_profiles": min(count, start + 64), "vectors": vector_count}), flush=True)
        store.client.flush(store.collection)
        actual = store.client.query(store.collection, filter="", output_fields=["count(*)"], consistency_level="Strong")[0]["count(*)"]
        assert actual == count * 4
        requirements = JobRequirements(required_skills=["Python", "PostgreSQL"], preferred_skills=["Docker"],
                                       location="SHANGHAI", min_education="Bachelor", min_experience_months=36,
                                       responsibilities=["Python PostgreSQL payment service development"])
        pipeline = Pipeline(models=models, vectors=lambda _: store)
        latencies = []
        summaries = []
        for _ in range(queries):
            with db.session() as session:
                job = db.Job(title="SYNTHETIC BENCH Python engineer", description="SYNTHETIC BENCHMARK",
                             requirements=requirements.model_dump(), status="completed")
                session.add(job)
                session.flush()
                run = db.MatchRun(job_id=job.id, job_snapshot={"title": job.title, "requirements": job.requirements})
                session.add(run)
                session.flush()
                run_id = run.id
            before = time.monotonic()
            pipeline.match({"run_id": run_id})
            latencies.append((time.monotonic() - before) * 1000)
            with db.session() as session:
                run = session.get(db.MatchRun, run_id)
                assert run.status == "completed" and len(run.results) == 20
                assert run.diagnostics["recalled"] == 100 and run.diagnostics["eligible"] == 100
                assert all(c["status"] == "pass" for r in run.results for c in r["score"]["conditions"])
                assert all(abs(sum(d["score"] * d["weight"] for d in r["score"]["dimensions"]) - r["score"]["total"]) <= .011 for r in run.results)
                summaries.append({"run_id": run_id, "diagnostics": run.diagnostics, "scoring_version": run.model_versions["scoring"]})
        with db.session() as session:
            from sqlalchemy import func
            assert session.scalar(select(func.count()).select_from(db.Talent)) == count
        report.update(status="passed", vectors=actual, models=versions, embedding_seconds=embedding_seconds,
                      embedding_vectors_per_second=vector_count / embedding_seconds, upsert_seconds=upsert_seconds,
                      embedding_retries=embedding_retries,
                      duration_seconds=time.monotonic() - started, match_latencies_ms=latencies,
                      match_p50_ms=statistics.median(latencies), match_p95_ms=max(latencies), matches=summaries)
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        try:
            if store is not None:
                try:
                    if store.client.has_collection(store.collection):
                        store.client.drop_collection(store.collection)
                    report["temporary_collection_deleted"] = True
                finally:
                    store.client.close()
            if benchmark_engine is not None:
                benchmark_engine.dispose()
            if created:
                with original_engine.begin() as connection:
                    connection.execute(text('DROP SCHEMA "' + namespace + '" CASCADE'))
                report["temporary_schema_deleted"] = True
        finally:
            original_engine.dispose()
            lock.release()
            redis.close()
            Path("/data/benchmark-profiles-10000.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({k: report.get(k) for k in ("status", "profiles", "vectors", "match_p50_ms", "match_p95_ms")}), flush=True)


if __name__ == "__main__":
    main()
