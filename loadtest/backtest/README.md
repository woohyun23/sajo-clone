# 백테스트 동기·비동기 부하 테스트

백테스트 실행을 HTTP 요청 안에서 완료하던 동기 구조와, 요청 저장 후 전용 Executor에서 실행하는
비동기 구조를 동일한 조건으로 비교한다.

이 테스트는 다음 시간을 구분해 기록한다.

- `POST Backtest Create`: 백테스트 생성 API가 `201 Created`를 반환하기까지 걸린 시간
- `Backtest End-to-End Completion`: POST 시작부터 상태가 `COMPLETED` 또는 `FAILED`가 될 때까지 걸린 시간
- `Backtest Completion Result`: 제한된 폴링 시간 안에 `COMPLETED`가 확인됐는지 나타내는 검증 샘플

API 응답시간이 짧아졌다는 사실만으로 실제 계산 성능이 개선됐다고 해석하지 않는다. 비동기 전환의
목적은 긴 계산을 HTTP 요청의 Critical Path에서 분리하는 것이므로 응답시간, 실제 완료시간, 완료율을
함께 비교해야 한다.

## 비교 대상

| 구분 | Git revision |
|---|---|
| 동기 실행 | `c07a8221^` |
| 비동기 전환 직후 | `c07a8221` |
| 최종 구현 확인 | `dev` 또는 테스트 작업 브랜치 |

과거 revision은 현재 작업 디렉터리를 checkout하지 말고 별도 Git worktree에서 실행하는 것을 권장한다.
두 revision의 애플리케이션은 동시에 실행하지 않고 동일한 인프라와 테스트 데이터로 순차 측정한다.

## 사전 조건

1. PostgreSQL, Redis, Kafka와 market-service를 기동한다.
2. market-service가 `http://localhost:8082/actuator/health`에서 정상 응답하는지 확인한다.
3. 테스트 사용자와 해당 사용자가 소유한 Strategy를 준비한다.
4. Strategy 종목의 REST 일봉이 요청한 `START_DATE ~ END_DATE` 범위에 저장돼 있어야 한다.
5. 동기·비동기 버전에서 같은 PostgreSQL 데이터 스냅샷을 사용한다.
6. JMeter 5.6.3 이상을 설치한다.

Gateway와 JWT 처리시간을 제외하고 market-service 경로만 비교하기 위해 기본 대상은 8082 직접 호출이다.

## 실행

필수 환경변수:

```bash
export USER_ID="테스트-사용자-UUID"
export STRATEGY_ID="테스트-전략-UUID"
```

기본 실행:

```bash
cd loadtest/backtest
./run-backtest-load.sh after
```

부하 조건 지정:

```bash
THREADS=30 \
RAMP_UP=10 \
LOOPS=1 \
START_DATE=2025-01-01 \
END_DATE=2025-12-31 \
INITIAL_CASH=10000000 \
./run-backtest-load.sh after
```

동기 버전 worktree에서는 같은 변수로 `before` 시나리오를 실행한다.

```bash
./run-backtest-load.sh before
```

`before`와 `after`는 결과 디렉터리를 구분하는 라벨일 뿐 애플리케이션 revision을 자동으로 변경하지
않는다. 실행 전에 반드시 `git rev-parse HEAD`로 대상 revision을 확인한다. 실행 revision은 결과의
`metadata.txt`에도 기록된다.

## 주요 옵션

| 환경변수 | 기본값 | 설명 |
|---|---:|---|
| `BASE_URL` | `localhost` | market-service 호스트 |
| `BASE_PORT` | `8082` | market-service 포트 |
| `THREADS` | `10` | 동시 사용자 수 |
| `RAMP_UP` | `10` | 스레드 생성 시간(초) |
| `LOOPS` | `1` | 스레드당 백테스트 생성 횟수 |
| `START_DATE` | `2026-09-11` | 백테스트 시작일 |
| `END_DATE` | `2026-09-25` | 백테스트 종료일 |
| `INITIAL_CASH` | `10000000` | 초기 투자금 |
| `POLL_INTERVAL_MS` | `250` | 상태 조회 간격 |
| `MAX_POLLS` | `240` | 최대 상태 조회 횟수 |

기본 폴링 한도는 약 60초다. 긴 기간을 테스트할 때는 `MAX_POLLS`를 늘린다.

## 권장 측정 순서

1. `THREADS=1`로 기능과 데이터 범위를 확인한다.
2. `THREADS=5`, `10`, `30`, `50`, `60` 순서로 증가시킨다.
3. 각 조건을 3회 실행한다.
4. 세 결과의 중앙값을 비교표에 사용한다.
5. 동기·비동기 실행 모두 동일한 데이터와 옵션을 사용한다.

현재 비동기 Executor는 core 2, max 5, queue 50이다. 60개 이상의 작업을 짧은 시간에 제출하면
작업 거부나 `REQUESTED` 고착 가능성을 함께 확인할 수 있다.

## 결과

결과는 다음 경로에 저장된다.

```text
loadtest/results/backtest/{실행시각}-{scenario}-t{threads}-l{loops}/
├── metadata.txt
├── jmeter.log
├── result.jtl
├── summary.md
└── report/
```

`results/`는 Git에서 제외된다. 이력서나 문서에 사용할 결과는 원본 JTL을 그대로 커밋하지 말고,
3회 결과의 중앙값과 측정 환경을 `result-summary.md`에 기록한다.

## 결과 해석 시 주의사항

- `POST Backtest Create`의 p95 감소는 HTTP 응답 대기시간 개선이다.
- `Backtest End-to-End Completion`은 실제 작업 완료까지의 시간이다.
- 비동기 버전은 POST 응답이 빨라도 완료율이 낮다면 개선으로 볼 수 없다.
- `FAILED`, 폴링 시간 초과, 작업 거부, `REQUESTED` 고착 건수를 함께 기록한다.
- 가장 좋은 한 번이 아니라 동일 조건 3회 결과의 중앙값을 사용한다.
- 머신 사양, 컨테이너 수, 테스트 데이터 행 수가 다르면 결과를 직접 비교하지 않는다.
