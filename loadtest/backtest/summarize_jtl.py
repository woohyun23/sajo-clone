#!/usr/bin/env python3

import csv
import math
import sys
from collections import defaultdict
from pathlib import Path


def percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * ratio) - 1)
    return ordered[index]


def as_success(value: str) -> bool:
    return value.strip().lower() == "true"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: summarize_jtl.py <result.jtl>", file=sys.stderr)
        return 2

    jtl_path = Path(sys.argv[1])
    if not jtl_path.is_file():
        print(f"JTL 파일을 찾을 수 없습니다: {jtl_path}", file=sys.stderr)
        return 2

    elapsed_by_label: dict[str, list[int]] = defaultdict(list)
    success_by_label: dict[str, int] = defaultdict(int)
    started_by_label: dict[str, list[int]] = defaultdict(list)
    finished_by_label: dict[str, list[int]] = defaultdict(list)
    started_at_millis: list[int] = []
    finished_at_millis: list[int] = []

    with jtl_path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        required = {"timeStamp", "elapsed", "label", "success"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            print(f"필수 JTL 컬럼이 없습니다: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

        for row in reader:
            label = row["label"]
            elapsed = int(row["elapsed"])
            started_at = int(row["timeStamp"])
            elapsed_by_label[label].append(elapsed)
            if as_success(row["success"]):
                success_by_label[label] += 1
            started_by_label[label].append(started_at)
            finished_by_label[label].append(started_at + elapsed)
            started_at_millis.append(started_at)
            finished_at_millis.append(started_at + elapsed)

    if not elapsed_by_label:
        print("JTL에 결과가 없습니다.", file=sys.stderr)
        return 1

    duration_seconds = max(
        (max(finished_at_millis) - min(started_at_millis)) / 1000,
        0.001,
    )

    print("# JMeter 결과 요약")
    print()
    print(f"- 원본: `{jtl_path}`")
    print(f"- 측정 구간: {duration_seconds:.3f}초")
    print()
    print("| Label | Samples | Success | Error % | Average ms | p50 ms | p90 ms | p95 ms | p99 ms |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    for label in sorted(elapsed_by_label):
        values = elapsed_by_label[label]
        count = len(values)
        success = success_by_label[label]
        error_percent = (count - success) / count * 100
        average = sum(values) / count
        print(
            f"| {label} | {count} | {success} | {error_percent:.2f} | "
            f"{average:.2f} | {percentile(values, 0.50)} | {percentile(values, 0.90)} | "
            f"{percentile(values, 0.95)} | {percentile(values, 0.99)} |"
        )

    post_count = len(elapsed_by_label.get("POST Backtest Create", []))
    post_success = success_by_label.get("POST Backtest Create", 0)
    completed = success_by_label.get("Backtest Completion Result", 0)
    post_started = started_by_label.get("POST Backtest Create", [])
    post_finished = finished_by_label.get("POST Backtest Create", [])

    print()
    print("## 핵심 검증")
    print()
    print(f"- 생성 요청 수: {post_count}")
    print(f"- 생성 요청 성공 수: {post_success}")
    print(f"- 완료 확인 성공 수: {completed}")
    if post_success:
        print(f"- 완료 확인 성공률: {completed / post_success * 100:.2f}%")
    else:
        print("- 완료 확인 성공률: 측정 불가")
    if post_started and post_finished:
        post_duration_seconds = max(
            (max(post_finished) - min(post_started)) / 1000,
            0.001,
        )
        print(f"- 생성 API 측정 구간: {post_duration_seconds:.3f}초")
        print(f"- 생성 요청 처리량: {post_count / post_duration_seconds:.2f} req/s")
    else:
        print("- 생성 요청 처리량: 측정 불가")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
