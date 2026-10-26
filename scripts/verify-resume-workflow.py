"""Real local-model checks; one case deliberately removes first-pass contacts."""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from talent.adapters import PrivateModels
from talent.config import settings
from talent.schemas import ResumeExtraction


class OmittedContactModels(PrivateModels):
    """Controlled omission after a real first response; all repair calls are real."""
    first_pass_contact_removed = False
    calls = 0

    def extract(self, schema, text, purpose):
        result = super().extract(schema, text, purpose)
        self.calls += 1
        if self.calls == 1 and schema is ResumeExtraction:
            self.first_pass_contact_removed = bool(result.phone or result.email)
            result = result.model_copy(deep=True)
            result.phone = result.email = None
            result.evidence = [e for e in result.evidence if e.field.split(".")[0] not in {"phone", "email"}]
        return result


def verify(ollama_url):
    os.environ["OLLAMA_URL"] = ollama_url
    settings.cache_clear()
    source = ("SYNTHETIC TEST RESUME - NOT A REAL PERSON\n姓名：合成流程验收甲\n"
              "邮箱：workflow-check@example.invalid\n技能：Python、SQL\n"
              "教育经历：2020年9月至2024年6月，就读合成测试大学，本科，软件工程专业。\n"
              "求职意向：Python工程师。\n")
    reports = []
    for case in ("complete", "controlled_omission", "source_missing"):
        models = OmittedContactModels() if case == "controlled_omission" else PrivateModels()
        text = "SYNTHETIC TEST RESUME - NOT A REAL PERSON\n技能：Python、SQL。" if case == "source_missing" else source
        start = time.monotonic()
        result = models.resume_with_report(text)
        report = result.report.model_dump()
        if case == "source_missing":
            assert report["quality_status"] == "partial"
            assert report["stop_reason"] == "no_progress"
            assert result.profile.name is None and result.profile.phone is None and result.profile.email is None
            assert not result.profile.education and not result.profile.experiences
        else:
            assert report["quality_status"] == "complete"
            assert result.profile.name == "合成流程验收甲"
            assert result.profile.email == "workflow-check@example.invalid"
            assert result.profile.skills and result.profile.education
            if case == "complete":
                assert report["retry_count"] == 0
            else:
                assert models.first_pass_contact_removed
                assert 1 <= report["retry_count"] <= 3
        for evidence in result.profile.evidence.values():
            for entry in evidence:
                assert entry.quote in text
                assert text[entry.start:entry.start + len(entry.quote)] == entry.quote
        encoded = json.dumps(report, ensure_ascii=False)
        assert "workflow-check@example.invalid" not in encoded and "合成流程验收甲" not in encoded
        reports.append({"case": case, "elapsed_seconds": round(time.monotonic() - start, 3),
                        "controlled_omission": case == "controlled_omission", "report": report})
        print(f"{case}: {report['quality_status']}, repairs={report['retry_count']}", flush=True)
    return {"status": "passed", "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "real local Qwen; omission case deliberately strips contacts after real first response; no database writes",
            "models": models.versions(), "cases": reports}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--output", default="data/resume-workflow-real.json")
    args = parser.parse_args()
    try:
        report = verify(args.ollama_url)
    except Exception as exc:
        report = {"status": "failed", "error_type": type(exc).__name__}
        print("Workflow verification failed: " + type(exc).__name__, file=sys.stderr)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
