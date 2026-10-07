#!/usr/bin/env python3

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any


PUBLISHED_PREFIX = "strategy_signal_published_total"
BLOCKED_PREFIX = "strategy_signal_duplicate_blocked_total"


def percentile(values: list[int], ratio: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    return ordered[max(0, math.ceil(len(ordered) * ratio) - 1)]


def parse_jtl(path: Path) -> dict[str, Any]:
    elapsed: list[int] = []
    successes = 0
    starts: list[int] = []
    finishes: list[int] = []

    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        required = {"timeStamp", "elapsed", "label", "success"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"필수 JTL 컬럼이 없습니다: {', '.join(sorted(missing))}")

        for row in reader:
            if row["label"] != "POST Strategy Evaluation":
                continue
            duration = int(row["elapsed"])
            started = int(row["timeStamp"])
            elapsed.append(duration)
            starts.append(started)
            finishes.append(started + duration)
            successes += row["success"].strip().lower() == "true"

    if not elapsed:
        raise ValueError("JTL에 POST Strategy Evaluation 결과가 없습니다.")

    duration_seconds = max((max(finishes) - min(starts)) / 1000, 0.001)
    count = len(elapsed)
    return {
        "request_count": count,
        "success_count": successes,
        "error_count": count - successes,
        "error_rate_percent": round((count - successes) / count * 100, 4),
        "duration_seconds": round(duration_seconds, 3),
        "throughput_rps": round(count / duration_seconds, 3),
        "average_ms": round(sum(elapsed) / count, 3),
        "p50_ms": percentile(elapsed, 0.50),
        "p90_ms": percentile(elapsed, 0.90),
        "p95_ms": percentile(elapsed, 0.95),
        "p99_ms": percentile(elapsed, 0.99),
    }


def parse_redis_info(path: Path) -> dict[str, float]:
    result: dict[str, float] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip().rstrip("\r")
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        try:
            result[key] = float(value)
        except ValueError:
            continue
    return result


def redis_delta(before: dict[str, float], after: dict[str, float], duration: float) -> dict[str, Any]:
    commands = after.get("total_commands_processed", 0) - before.get("total_commands_processed", 0)
    return {
        "commands_delta": int(commands),
        "commands_per_second": round(commands / max(duration, 0.001), 3),
        "cpu_sys_seconds_delta": round(after.get("used_cpu_sys", 0) - before.get("used_cpu_sys", 0), 6),
        "cpu_user_seconds_delta": round(after.get("used_cpu_user", 0) - before.get("used_cpu_user", 0), 6),
        "used_memory_start_bytes": int(before.get("used_memory", 0)),
        "used_memory_end_bytes": int(after.get("used_memory", 0)),
        "used_memory_peak_end_bytes": int(after.get("used_memory_peak", 0)),
    }


def parse_offset(path: Path) -> int:
    value = path.read_text(encoding="utf-8").strip()
    return int(value or "0")


def parse_prometheus_directory(path: Path) -> dict[str, float | None]:
    totals: dict[str, float] = {"published": 0.0, "blocked": 0.0}
    found = {"published": False, "blocked": False}

    for metrics_file in sorted(path.glob("*.prom")):
        for raw_line in metrics_file.read_text(encoding="utf-8").splitlines():
            if not raw_line or raw_line.startswith("#"):
                continue
            match = re.match(r"^([^\s{]+)(?:\{[^}]*\})?\s+([-+0-9.eE]+)$", raw_line)
            if not match:
                continue
            metric_name, raw_value = match.groups()
            if metric_name.startswith(PUBLISHED_PREFIX) and not metric_name.endswith("_created"):
                totals["published"] += float(raw_value)
                found["published"] = True
            elif metric_name.startswith(BLOCKED_PREFIX) and not metric_name.endswith("_created"):
                totals["blocked"] += float(raw_value)
                found["blocked"] = True

    return {
        key: round(totals[key], 6) if found[key] else None
        for key in totals
    }


def counter_delta(before: float | None, after: float | None) -> float | None:
    if after is None:
        return None
    # Micrometer Counter는 최초 increment 시점에 지연 등록될 수 있다. 사전 스냅샷에 없고
    # 사후에 생겼다면 이 프로세스에서 0부터 시작한 것으로 계산한다. 사후에도 없으면 해당
    # revision에 메트릭 자체가 없는 경우이므로 측정 불가(None)를 유지한다.
    return round(after - (before or 0.0), 6)


def display(value: Any, suffix: str = "") -> str:
    return "측정 불가" if value is None else f"{value}{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jtl", type=Path, required=True)
    parser.add_argument("--redis-before", type=Path, required=True)
    parser.add_argument("--redis-after", type=Path, required=True)
    parser.add_argument("--kafka-before", type=Path, required=True)
    parser.add_argument("--kafka-after", type=Path, required=True)
    parser.add_argument("--prom-before", type=Path, required=True)
    parser.add_argument("--prom-after", type=Path, required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()

    api = parse_jtl(args.jtl)
    redis = redis_delta(
        parse_redis_info(args.redis_before),
        parse_redis_info(args.redis_after),
        api["duration_seconds"],
    )
    kafka_before = parse_offset(args.kafka_before)
    kafka_after = parse_offset(args.kafka_after)
    kafka_delta = kafka_after - kafka_before
    prom_before = parse_prometheus_directory(args.prom_before)
    prom_after = parse_prometheus_directory(args.prom_after)
    prom = {
        "published_delta": counter_delta(prom_before["published"], prom_after["published"]),
        "blocked_delta": counter_delta(prom_before["blocked"], prom_after["blocked"]),
    }

    duplicate_published = max(kafka_delta - min(kafka_delta, 1), 0)
    duplicate_rate = duplicate_published / api["request_count"] * 100
    summary = {
        "scenario": args.scenario,
        "threads": args.threads,
        "api": api,
        "kafka": {
            "offset_before": kafka_before,
            "offset_after": kafka_after,
            "signal_published_delta": kafka_delta,
            "duplicate_signal_count": duplicate_published,
            "duplicate_signal_rate_percent": round(duplicate_rate, 4),
        },
        "prometheus": prom,
        "redis": redis,
    }
    args.json_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("# Strategy Redis 부하 테스트 결과")
    print()
    print(f"- 시나리오: `{args.scenario}`")
    print(f"- 동시 사용자: {args.threads}")
    print(f"- 요청/성공/오류: {api['request_count']} / {api['success_count']} / {api['error_count']}")
    print(f"- 처리량: {api['throughput_rps']} req/s")
    print(f"- HTTP 오류율: {api['error_rate_percent']}%")
    print()
    print("| Average | p50 | p90 | p95 | p99 |")
    print("|---:|---:|---:|---:|---:|")
    print(f"| {api['average_ms']}ms | {api['p50_ms']}ms | {api['p90_ms']}ms | {api['p95_ms']}ms | {api['p99_ms']}ms |")
    print()
    print("## Signal 정합성")
    print()
    print(f"- Kafka Topic 메시지 증가량: {kafka_delta}")
    print(f"- 중복 Signal 수: {duplicate_published}")
    print(f"- 중복 Signal 발행률: {duplicate_rate:.4f}% (중복 Signal 수 / 전체 평가 요청 수)")
    print(f"- Prometheus 발행 카운터 증가량: {display(prom['published_delta'])}")
    print(f"- Prometheus 차단 카운터 증가량: {display(prom['blocked_delta'])}")
    print()
    print("## Redis")
    print()
    print(f"- 명령 처리 증가량: {redis['commands_delta']}")
    print(f"- 측정 구간 평균 명령 처리량: {redis['commands_per_second']} commands/s")
    print(f"- CPU sys/user 증가: {redis['cpu_sys_seconds_delta']}s / {redis['cpu_user_seconds_delta']}s")
    print(f"- 사용 메모리 시작/종료: {redis['used_memory_start_bytes']} / {redis['used_memory_end_bytes']} bytes")
    print()
    print("> 적용 전 revision에는 커스텀 Prometheus 카운터가 없으므로 Kafka 증가량을 전후 공통 기준으로 사용한다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
