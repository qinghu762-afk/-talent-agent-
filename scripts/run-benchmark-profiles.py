"""Sample host GPU and run the isolated full-match benchmark; restore only our worker."""
import json
import runpy
import subprocess
import time
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    stage = root / ".tmp" / "profile-benchmark"
    stage.mkdir(parents=True, exist_ok=True)
    script = runpy.run_path(str(root / "scripts" / "verify-restore.py"))["SNAPSHOT"]

    def compose(*args, **kwargs):
        return subprocess.run(["docker", "compose", "-p", "talent-agent", *args], cwd=root, check=True, **kwargs)

    def snapshot():
        value = compose("exec", "-T", "api", "python", "-", input=script, capture_output=True, text=True, encoding="utf-8")
        return json.loads(value.stdout)

    was_running = bool(compose("ps", "--status", "running", "-q", "worker", capture_output=True, text=True).stdout.strip())
    samples = []
    before = snapshot()
    try:
        if was_running:
            compose("stop", "-t", "960", "worker")
        with (root / "scripts" / "benchmark-profiles.py").open("rb") as source, (stage / "run.log").open("wb") as log:
            process = subprocess.Popen(["docker", "compose", "-p", "talent-agent", "exec", "-T", "api", "python", "-"],
                                       cwd=root, stdin=source, stdout=log, stderr=subprocess.STDOUT)
            while process.poll() is None:
                try:
                    result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                            capture_output=True, text=True, check=True, timeout=5)
                    samples.append({"time": time.time(), "used_mib": sum(int(s) for s in result.stdout.splitlines() if s.strip())})
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
                time.sleep(1)
            if process.returncode:
                raise RuntimeError("Profile benchmark failed; inspect .tmp/profile-benchmark/run.log")
        report_path = root / "data" / "benchmark-profiles-10000.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["status"] == "passed" and report["temporary_schema_deleted"] and report["temporary_collection_deleted"]
        after = snapshot()
        assert before["tables"] == after["tables"] and before["originals"] == after["originals"]
        report["source_facts_and_originals_unchanged"] = True
        report["host_gpu_samples"] = len(samples)
        report["host_gpu_peak_used_mib"] = max((s["used_mib"] for s in samples), default=None)
        report["gpu_scope"] = "total host GPU memory, including other processes; sampled about once per second"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: report[k] for k in ("status", "profiles", "vectors", "match_p50_ms", "match_p95_ms", "host_gpu_peak_used_mib")}))
    finally:
        (root / "data" / "benchmark-profiles-gpu.json").write_text(json.dumps({"samples": samples}, indent=2), encoding="utf-8")
        if was_running:
            compose("up", "-d", "--no-deps", "--no-build", "--pull", "never", "worker")


if __name__ == "__main__":
    main()
