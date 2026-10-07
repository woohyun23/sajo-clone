#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
loadtest_dir="$(cd "${script_dir}/.." && pwd)"
repo_dir="$(cd "${loadtest_dir}/.." && pwd)"
app_repo_dir="${APP_REPO_DIR:-${repo_dir}}"

scenario="${1:-after}"
total_requests="${TOTAL_REQUESTS:-100}"
threads="${THREADS:-10}"
ramp_up="${RAMP_UP:-1}"
base_host="${BASE_HOST:-localhost}"
target_ports="${TARGET_PORTS:-8082}"
internal_secret="${INTERNAL_SECRET:-local-dev-internal-api-secret-do-not-use-in-prod}"
strategy_id="${STRATEGY_ID:-11111111-1111-4111-8111-111111111111}"
stock_code="${STOCK_CODE:-999999}"
current_price="${CURRENT_PRICE:-65000}"
postgres_container="${POSTGRES_CONTAINER:-sajo-postgres}"
postgres_user="${POSTGRES_USER:-postgres}"
postgres_database="${POSTGRES_DATABASE:-sajo}"
redis_container="${REDIS_CONTAINER:-sajo-redis}"
redis_password="${REDIS_PASSWORD:-redis}"
kafka_container="${KAFKA_CONTAINER:-sajo-kafka-loadtest}"
kafka_topic="${KAFKA_TOPIC:-trading.signal.generated}"
generate_report="${GENERATE_REPORT:-false}"

if [[ "${scenario}" != "before" && "${scenario}" != "after" && "${scenario}" != "dev" ]]; then
  echo "scenario는 before, after, dev 중 하나여야 합니다." >&2
  exit 2
fi

if (( total_requests <= 0 || threads <= 0 || total_requests % threads != 0 )); then
  echo "TOTAL_REQUESTS는 THREADS로 나누어떨어지는 양수여야 합니다." >&2
  exit 2
fi
loops=$((total_requests / threads))

if ! command -v jmeter >/dev/null 2>&1; then
  echo "jmeter 명령을 찾을 수 없습니다. Apache JMeter 5.6.3 이상을 설치해 주세요." >&2
  exit 1
fi

current_revision="$(git -C "${app_repo_dir}" rev-parse HEAD)"
if [[ -n "${EXPECTED_REVISION:-}" && "${current_revision}" != "$(git -C "${repo_dir}" rev-parse "${EXPECTED_REVISION}")" ]]; then
  echo "현재 revision(${current_revision})이 EXPECTED_REVISION(${EXPECTED_REVISION})과 다릅니다." >&2
  exit 2
fi

run_id="$(date '+%Y%m%d-%H%M%S')-${scenario}-n${total_requests}-t${threads}"
result_dir="${loadtest_dir}/results/strategy-redis/${run_id}"
prom_before_dir="${result_dir}/prometheus-before"
prom_after_dir="${result_dir}/prometheus-after"
mkdir -p "${prom_before_dir}" "${prom_after_dir}"

ports=()
IFS=',' read -r -a raw_ports <<< "${target_ports}"
for port in "${raw_ports[@]}"; do
  port="${port//[[:space:]]/}"
  [[ -n "${port}" ]] && ports+=("${port}")
done
if (( ${#ports[@]} == 0 )); then
  echo "TARGET_PORTS에 하나 이상의 포트가 필요합니다." >&2
  exit 2
fi

capture_prometheus() {
  local destination="$1"
  local port
  for port in "${ports[@]}"; do
    curl --fail --silent --show-error \
      "http://${base_host}:${port}/actuator/prometheus" \
      > "${destination}/${port}.prom"
  done
}

capture_redis() {
  local destination="$1"
  docker exec -e REDISCLI_AUTH="${redis_password}" "${redis_container}" \
    redis-cli --no-auth-warning INFO > "${destination}"
}

capture_kafka_offset() {
  local destination="$1"
  local offsets_file="${destination}.raw"
  docker exec "${kafka_container}" \
    /opt/kafka/bin/kafka-get-offsets.sh \
    --bootstrap-server localhost:9092 \
    --topic "${kafka_topic}" \
    --time -1 > "${offsets_file}"
  awk -F: '{ total += $3 } END { print total + 0 }' "${offsets_file}" > "${destination}"
  rm "${offsets_file}"
}

for port in "${ports[@]}"; do
  curl --fail --silent --show-error "http://${base_host}:${port}/actuator/health" >/dev/null
done

docker exec -i "${postgres_container}" psql \
  -v ON_ERROR_STOP=1 \
  -U "${postgres_user}" \
  -d "${postgres_database}" \
  < "${script_dir}/seed/performance-test-data.sql" >/dev/null

STRATEGY_ID="${strategy_id}" \
REDIS_CONTAINER="${redis_container}" \
REDIS_PASSWORD="${redis_password}" \
  "${script_dir}/cleanup-strategy-redis.sh"

capture_prometheus "${prom_before_dir}"
capture_redis "${result_dir}/redis-before.info"
capture_kafka_offset "${result_dir}/kafka-before.offset"

{
  echo "run_id=${run_id}"
  echo "scenario=${scenario}"
  echo "git_commit=${current_revision}"
  echo "git_branch=$(git -C "${app_repo_dir}" branch --show-current)"
  echo "app_repo_dir=${app_repo_dir}"
  echo "started_at=$(date -Iseconds)"
  echo "base_host=${base_host}"
  echo "target_ports=${target_ports}"
  echo "instance_count=${#ports[@]}"
  echo "total_requests=${total_requests}"
  echo "threads=${threads}"
  echo "ramp_up=${ramp_up}"
  echo "loops=${loops}"
  echo "strategy_id=${strategy_id}"
  echo "stock_code=${stock_code}"
  echo "current_price=${current_price}"
  echo "kafka_topic=${kafka_topic}"
  echo "jmeter_version=$(jmeter --version 2>&1 | sed -n 's/.*Apache JMeter \([0-9][0-9.]*\).*/\1/p' | head -1)"
  echo "machine=$(uname -a)"
} > "${result_dir}/metadata.txt"

echo "Strategy Redis 부하 테스트 시작: ${run_id}"

jmeter_args=(
  -n
  -t "${loadtest_dir}/strategy-redis-performance.jmx"
  -j "${result_dir}/jmeter.log"
  -JBASE_HOST="${base_host}"
  -JTARGET_PORTS="${target_ports}"
  -JINTERNAL_SECRET="${internal_secret}"
  -JSTOCK_CODE="${stock_code}"
  -JCURRENT_PRICE="${current_price}"
  -JTHREADS="${threads}"
  -JRAMP_UP="${ramp_up}"
  -JLOOPS="${loops}"
  -l "${result_dir}/result.jtl"
)
if [[ "${generate_report}" == "true" ]]; then
  jmeter_args+=( -e -o "${result_dir}/report" )
fi
jmeter "${jmeter_args[@]}"

capture_prometheus "${prom_after_dir}"
capture_redis "${result_dir}/redis-after.info"
capture_kafka_offset "${result_dir}/kafka-after.offset"

python3 "${script_dir}/summarize_run.py" \
  --jtl "${result_dir}/result.jtl" \
  --redis-before "${result_dir}/redis-before.info" \
  --redis-after "${result_dir}/redis-after.info" \
  --kafka-before "${result_dir}/kafka-before.offset" \
  --kafka-after "${result_dir}/kafka-after.offset" \
  --prom-before "${prom_before_dir}" \
  --prom-after "${prom_after_dir}" \
  --scenario "${scenario}" \
  --threads "${threads}" \
  --json-out "${result_dir}/summary.json" \
  | tee "${result_dir}/summary.md"

{
  echo "finished_at=$(date -Iseconds)"
  echo "summary=${result_dir}/summary.md"
} >> "${result_dir}/metadata.txt"

echo "완료: ${result_dir}"
