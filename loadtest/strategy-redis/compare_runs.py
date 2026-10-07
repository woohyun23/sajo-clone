#!/usr/bin/env python3

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


FIELDS = {
    "처리량(req/s)": ("api", "throughput_rps"),
    "평균(ms)": ("api", "average_ms"),
    "p50(ms)": ("api", "p50_ms"),
    "p90(ms)": ("api", "p90_ms"),
    "p95(ms)": ("api", "p95_ms"),
    "p99(ms)": ("api", "p99_ms"),
    "오류율(%)": ("api", "error_rate_percent"),
    "Kafka Signal 수": ("kafka", "signal_published_delta"),
    "중복 Signal 수": ("kafka", "duplicate_signal_count"),
    "중복 Signal 발행률(%)": ("kafka", "duplicate_signal_rate_percent"),
    "Redis 명령 수": ("redis", "commands_delta"),
    "Redis 명령/초": ("redis", "commands_per_second"),
}


def load(paths: list[Path]) -> list[dict[str, Any]]:
    if len(paths) != 3:
        raise ValueError("before와 after는 각각 정확히 3개의 summary.json이 필요합니다.")
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def median(rows: list[dict[str, Any]], path: tuple[str, str]) -> float:
    return statistics.median(float(row[path[0]][path[1]]) for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, nargs="+", required=True)
    parser.add_argument("--after", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    before = load(args.before)
    after = load(args.after)
    lines = [
        "# Redis Lua 적용 전후 3회 중앙값 비교",
        "",
        "| 지표 | 적용 전 | 적용 후 |",
        "|---|---:|---:|",
    ]
    values: dict[str, tuple[float, float]] = {}
    for label, path in FIELDS.items():
        pair = (median(before, path), median(after, path))
        values[label] = pair
        lines.append(f"| {label} | {pair[0]:.4f} | {pair[1]:.4f} |")

    before_duplicates, after_duplicates = values["중복 Signal 수"]
    if before_duplicates > 0:
        reduction = (before_duplicates - after_duplicates) / before_duplicates * 100
        lines.extend(["", f"- 중복 Signal 감소율: **{reduction:.4f}%**"])
    else:
        lines.extend(["", "- 중복 Signal 감소율: 적용 전 중복 수가 0이어서 계산하지 않음"])

    lines.extend([
        "- 각 값은 동일 조건 3회 실행 결과의 중앙값이다.",
        "- 이 결과는 전략 평가 단계의 반복 Signal 차단만 검증하며 전체 주문 Exactly-once를 의미하지 않는다.",
    ])
    output = "\n".join(lines) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
