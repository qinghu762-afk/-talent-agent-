"""Operator commands; never substitute synthetic outputs for real service results."""
import argparse
import json
import sys

from .acceptance import benchmark, generate_fixtures, reindex, verify, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="人才工作台恢复与真实服务验收")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("reindex", help="重置派生索引并将所有人才的当前版本加入任务队列（请先停止 worker/beat）")
    fixtures = commands.add_parser("fixtures", help="生成 30 份合成简历、5 个岗位和负向测试文件")
    fixtures.add_argument("--output", required=True)
    fixtures.add_argument("--label", help="New synthetic source label to avoid reusing previous extraction caches")
    fixtures.add_argument("--scan-font", help="Optional local TrueType/OpenType font for representative scans; requires Pillow")
    check = commands.add_parser("verify", help="通过真实 API 验收；会向目标环境写入合成验收数据")
    check.add_argument("--base-url", default="http://127.0.0.1:8080")
    check.add_argument("--username", default="admin")
    check.add_argument("--password-env", default="TALENT_ACCEPTANCE_PASSWORD")
    check.add_argument("--fixtures", required=True)
    check.add_argument("--timeout", type=float, default=7200)
    check.add_argument("--output", required=True)
    bench = commands.add_parser("benchmark", help="在临时 Milvus 集合运行真实本地向量测试；请先停止 worker")
    bench.add_argument("--count", type=int, default=10000)
    bench.add_argument("--queries", type=int, default=100)
    bench.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "reindex":
            result = reindex()
        elif args.command == "fixtures":
            manifest = generate_fixtures(args.output, label=args.label, font_path=args.scan_font)
            result = {"output": args.output, "resumes": len(manifest["resumes"]), "jobs": len(manifest["jobs"])}
        elif args.command == "verify":
            result = verify(args.base_url, args.username, args.password_env, args.fixtures, args.timeout)
            write_json(args.output, result)
        else:
            result = benchmark(args.count, args.queries)
            write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        # Never print response bodies, URLs, environment variables or passwords.
        result = {"status": "failed", "command": args.command, "error_type": type(exc).__name__}
        if isinstance(exc, (AssertionError, ValueError)):
            result["detail"] = str(exc)
        if args.command in {"verify", "benchmark"}:
            write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
