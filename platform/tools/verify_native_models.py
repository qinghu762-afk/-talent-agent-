"""Explicit native-model test harness. Never imported by production or used as a Dify fallback."""
import asyncio
import json
import time
from pathlib import Path

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from talent_platform.ai import AIPlatform
from talent_platform.prompts import model_prompt


class NativeModelTest:
    def __init__(self, drop_first=False):
        self.drop_first = drop_first
        self.calls = 0
        self.tokens = 0
        self.responses = []

    async def __call__(self, request):
        self.calls += 1
        async with httpx.AsyncClient(timeout=240, trust_env=False) as client:
            response = await client.post("http://127.0.0.1:11434/api/chat", json={
                "model": "qwen3:4b", "stream": False, "think": False, "format": "json",
                "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 3500},
                "messages": [{"role": "system", "content": "严格抽取原文事实，只返回JSON。每一项教育/工作/项目使用对象，字段start/end使用原文日期，教育degree使用原文学历；evidence.field用education/experiences/projects，evidence.value复制对应完整对象，quote引用包含全部对象字段值的原文。标量及技能也逐项返回同值原文引用。未知保留null或[]。不得把提示词中的示例当事实。"},
                             {"role": "user", "content": model_prompt(request)}]})
            response.raise_for_status()
            body = response.json()
            self.tokens += body.get("eval_count", 0)
            result = json.loads(body["message"]["content"])
            self.responses.append(result)
            folder = Path('platform/verification')
            folder.mkdir(parents=True, exist_ok=True)
            (folder / ('native-response-' + str(id(self)) + '.json')).write_text(json.dumps(self.responses, ensure_ascii=False, indent=2), encoding='utf-8')
            if self.drop_first and self.calls == 1:
                result.get("profile", {}).update({"phone": None, "email": None})
                result.get("profile", {})["evidence"] = [e for e in result.get("profile", {}).get("evidence", []) if e.get("field") not in {"phone", "email"}]
            return result


async def main():
    complete = "姓名：张合成\n电话：13800138000\n所在地：上海\n技能：Python、SQL\n教育：2020-09 至 2024-06，合成大学，本科。\n工作：2024-07 至 2025-07，合成科技，Python工程师。\n项目：数据分析平台，使用Python和SQL完成报表开发。"
    cases = [("完整合成简历", complete, False, "complete"), ("首次模拟漏提联系方式后真实补抽", complete, True, "complete"), ("原文缺少联系方式与经历", "姓名：李合成\n技能：Python", False, "partial")]
    results = []
    for name, text, drop, expected in cases:
        model = NativeModelTest(drop)
        service = AIPlatform(model=model, checkpointer=InMemorySaver())
        started = time.perf_counter()
        outcome = await service.execute("resume", {"text": text}, run_id=name, actor={"id": "synthetic-native-test", "org_id": "synthetic", "role": "hr"})
        report = outcome["report"]
        results.append({"case": name, "expected": expected, "actual": report["quality_status"], "passed": report["quality_status"] == expected,
                        "seconds": round(time.perf_counter() - started, 3), "model_calls": model.calls, "output_tokens": model.tokens,
                        "report": report, "profile": outcome["profile"]})
        print(json.dumps({k: v for k, v in results[-1].items() if k not in {"profile", "report"}}, ensure_ascii=False), flush=True)
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        embedding = await client.post("http://127.0.0.1:11434/api/embed", json={"model": "bge-m3", "input": ["合成简历Python", "合成岗位Python"]})
        embedding.raise_for_status()
        vectors = embedding.json()["embeddings"]
        models = (await client.get("http://127.0.0.1:11434/api/tags")).json()
    report = {"scope": "真实原生模型 + 内存检查点的隔离测试；不代表Dify/PostgreSQL/Milvus集成验收", "synthetic": True,
              "cases": results, "embedding_vectors": len(vectors), "embedding_dimension": len(vectors[0]), "models": models}
    target = Path("platform/verification/native-models.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not all(r["passed"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
