# Redis Lua Signal 중복 차단 부하 테스트

서로 다른 시세 이벤트가 동일 전략의 BUY 조건을 연속해서 만족할 때, Redis Lua 기반 소유권 토큰
상태 머신이 Signal을 한 번만 발행하도록 제어하는지와 그 처리 비용을 측정한다.

## 검증 범위

- 적용 전: `9cb640b9^`
- 적용 후: `9cb640b9`
- 최종 구현 확인: `dev`
- API: `POST /internal/v1/strategies/evaluations`
- Kafka Topic: `trading.signal.generated`
- 테스트 전략 상태: 하나의 ACTIVE 전략, 고정 현재가 `65,000`, 매수 조건가 `70,000`
- 모든 요청은 서로 다른 `sourceEventId`를 사용한다.

적용 전 revision에는 `strategy_signal_published_total`과
`strategy_signal_duplicate_blocked_total`이 존재하지 않는다. 따라서 Kafka Topic의 메시지 증가량을
전후 공통 기준으로 사용하고, 적용 후에만 Prometheus 카운터와 교차 검증한다.

이 테스트는 전략 평가 단계의 반복 Signal 차단을 검증한다. Redis 상태 변경과 Kafka 발행은 하나의
트랜잭션이 아니므로, 결과를 전체 자동매매 과정의 Exactly-once 보장으로 표현하지 않는다.

## 파일 구성

```text
loadtest/
├── strategy-redis-performance.jmx
└── strategy-redis/
    ├── README.md
    ├── account_stub.py
    ├── cleanup-strategy-redis.sh
    ├── compare_runs.py
    ├── result-summary.md
    ├── run-strategy-redis-load.sh
    ├── summarize_run.py
    └── seed/performance-test-data.sql
```

`account_stub.py`는 부하를 만드는 도구가 아니라, 적용 후 구현에 추가된 Account Service 진입가 조회가
네트워크 상태에 따라 전후 비교를 왜곡하지 않도록 고정 응답을 주는 테스트 fixture다. JMeter만 실제
전략 평가 API 부하를 발생시킨다.

## 1. revision별 애플리케이션 준비

현재 작업 디렉터리를 반복해서 checkout하지 말고 별도 worktree를 만든다.

```bash
git worktree add ../sajo-signal-before '9cb640b9^'
git worktree add ../sajo-signal-after 9cb640b9
```

PostgreSQL, Redis, Kafka는 두 revision 모두 동일한 컨테이너를 사용하며, before와 after는 동시에
실행하지 않고 순차 측정한다. 테스트 시작 전 Docker 컨테이너 상태를 확인한다.

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
```

## 2. Account Service 고정 응답 실행

적용 후 코드는 BUY Signal 발행 후 Account Service에서 평균 매입가를 조회한다. 이 호출을 같은 조건으로
고정하기 위해 다음 스텁을 실행하고 market-service에 `USER_SERVICE_URL=http://localhost:18081`을
설정한다.

```bash
python3 loadtest/strategy-redis/account_stub.py
```

스텁 확인:

```bash
curl http://localhost:18081/actuator/health
```

## 3. market-service 실행

각 worktree에서 같은 환경변수로 실행한다. 로컬 PostgreSQL에 스키마가 이미 준비된 측정 환경에서는
Flyway 상태 차이로 revision 비교가 중단되지 않도록 필요 시 `--spring.flyway.enabled=false`를 사용한다.

```bash
USER_SERVICE_URL=http://localhost:18081 \
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
./gradlew :market-service:bootRun \
  --args='--spring.profiles.active=local --spring.flyway.enabled=false --server.port=8082 --management.tracing.sampling.probability=0.0 --spring.cloud.openfeign.client.config.accountHoldingFeignClient.url=http://localhost:18081'
```

두 인스턴스 검증은 동일 revision에서 포트만 다르게 실행한다.

```bash
# 첫 번째 터미널: --server.port=8082
# 두 번째 터미널: --server.port=8083
```

두 프로세스는 동일 PostgreSQL, Redis, Kafka를 사용해야 한다. Prometheus 카운터는 프로세스별이므로
실행 스크립트가 두 `/actuator/prometheus` 값을 합산한다. 로컬 Zipkin을 함께 띄우지 않는 경우에는
위 예시처럼 tracing sampling을 0으로 고정해 실패한 trace export가 성능 수치에 섞이지 않게 한다.

## 4. 단일 실행

JMeter 5.6.3 이상이 필요하다. 스크립트는 다음을 자동 수행한다.

1. 실제 `p_strategies` 테이블에 고정 테스트 전략 upsert
2. 해당 전략에 속한 Redis 키만 삭제 (`FLUSHALL` 사용 안 함)
3. Prometheus, Redis INFO, Kafka Topic end offset 사전 스냅샷
4. JMeter 실행
5. 사후 스냅샷과 `summary.md`, `summary.json` 생성

```bash
cd /path/to/sajo-clone/loadtest/strategy-redis

TOTAL_REQUESTS=100 \
THREADS=10 \
TARGET_PORTS=8082 \
APP_REPO_DIR=/path/to/sajo-signal-before \
EXPECTED_REVISION='9cb640b9^' \
./run-strategy-redis-load.sh before
```

적용 후:

```bash
TOTAL_REQUESTS=100 \
THREADS=10 \
TARGET_PORTS=8082 \
APP_REPO_DIR=/path/to/sajo-signal-after \
EXPECTED_REVISION=9cb640b9 \
./run-strategy-redis-load.sh after
```

멀티 인스턴스에서는 JMeter 스레드를 두 포트에 분산한다.

```bash
TOTAL_REQUESTS=1000 THREADS=20 TARGET_PORTS=8082,8083 ./run-strategy-redis-load.sh after
```

`TOTAL_REQUESTS`는 `THREADS`로 나누어떨어져야 한다. HTML 리포트가 필요하면
`GENERATE_REPORT=true`를 추가한다. `APP_REPO_DIR`은 실제 실행 중인 market-service를 빌드한
worktree 경로다. 스크립트 파일은 현재 테스트 작업 브랜치에 있으므로 old revision worktree 안에서
실행하지 않고, 이 경로를 통해 측정 대상 revision을 검증·기록한다.

## 5. 시나리오와 3회 중앙값

요청 수 `100, 1,000, 5,000, 10,000`과 동시 사용자 `1, 10, 20, 50, 100`을 조합한다.
단, `요청 수 >= 동시 사용자`이며 나누어떨어지는 조합만 실행한다. 각 revision과 조건을 3회 실행한다.

세 실행의 `summary.json`을 비교한다.

```bash
python3 compare_runs.py \
  --before /path/before-run-1/summary.json /path/before-run-2/summary.json /path/before-run-3/summary.json \
  --after /path/after-run-1/summary.json /path/after-run-2/summary.json /path/after-run-3/summary.json \
  --output comparison.md
```

결과 디렉터리:

```text
loadtest/results/strategy-redis/{실행시각}-{scenario}-n{요청수}-t{스레드수}/
├── metadata.txt
├── result.jtl
├── jmeter.log
├── summary.md
├── summary.json
├── redis-before.info
├── redis-after.info
├── kafka-before.offset
├── kafka-after.offset
├── prometheus-before/
└── prometheus-after/
```

원본 결과는 `.gitignore`에 의해 제외된다. 최종 중앙값과 환경은 `result-summary.md`에 기록한다.

## 지표 해석

- Kafka Signal 증가량: 적용 전후 공통 Signal 발행 기준
- Prometheus 발행/차단 증가량: 적용 후 교차 검증 기준
- 중복 Signal 수: `max(Kafka Signal 증가량 - 1, 0)`
- 중복 Signal 발행률: `중복 Signal 수 / 전체 평가 요청 수 × 100`
- 중복 Signal 감소율: `(적용 전 중복 수 - 적용 후 중복 수) / 적용 전 중복 수 × 100`
- Redis commands/s: 테스트 구간 `total_commands_processed` 증가량 / JMeter 측정 구간
- Redis CPU: INFO의 누적 sys/user CPU 값 차이
- Redis 메모리: 테스트 시작/종료 `used_memory`와 종료 시 `used_memory_peak`

`instantaneous_ops_per_sec`는 한 시점의 순간값이라 짧은 테스트의 대표값으로 쓰지 않는다. 개별 평가
응답시간이 Lua 연산 때문에 소폭 증가하더라도 Signal 중복 감소와 분리해서 기록한다.

## 기대 결과와 실패 판정

하나의 ACTIVE 전략에 모두 다른 이벤트 ID로 동일 BUY 조건을 보낼 때:

- 적용 전: Kafka Signal 증가량이 성공한 평가 요청 수와 같아야 한다.
- 적용 후: Kafka Signal 증가량 1, Prometheus 발행 증가량 1, 차단 증가량 `성공 요청 수 - 1`이어야 한다.
- 멀티 인스턴스 적용 후에도 Kafka Signal 증가량은 1이어야 한다.
- HTTP 오류가 있으면 Signal 수 비교 전에 오류 원인을 해결하고 해당 실행을 폐기한다.

> 매우 짧은 테스트에서는 첫 요청이 완료 상태를 만들기 전에 다른 요청이 `PROCESSING`으로 차단되므로
> 결과는 같지만, 이 테스트만으로 Kafka 발행 성공 후 Redis 완료 전 프로세스 종료 구간까지 검증되지는 않는다.
