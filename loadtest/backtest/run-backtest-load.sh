#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
loadtest_dir="$(cd "${script_dir}/.." && pwd)"

scenario="${1:-after}"
threads="${THREADS:-10}"
ramp_up="${RAMP_UP:-10}"
loops="${LOOPS:-1}"
base_url="${BASE_URL:-localhost}"
base_port="${BASE_PORT:-8082}"
start_date="${START_DATE:-2026-09-11}"
end_date="${END_DATE:-2026-09-25}"
initial_cash="${INITIAL_CASH:-10000000}"
poll_interval_ms="${POLL_INTERVAL_MS:-250}"
max_polls="${MAX_POLLS:-240}"

if [[ -z "${USER_ID:-}" ]]; then
  echo "USER_ID 환경변수가 필요합니다." >&2
  exit 1
fi

if [[ -z "${STRATEGY_ID:-}" ]]; then
  echo "STRATEGY_ID 환경변수가 필요합니다." >&2
  exit 1
fi

if ! command -v jmeter >/dev/null 2>&1; then
  echo "jmeter 명령을 찾을 수 없습니다. Apache JMeter 5.6.3 이상을 설치해 주세요." >&2
  exit 1
fi

run_id="$(date '+%Y%m%d-%H%M%S')-${scenario}-t${threads}-l${loops}"
result_dir="${loadtest_dir}/results/backtest/${run_id}"
report_dir="${result_dir}/report"
jtl_file="${result_dir}/result.jtl"
metadata_file="${result_dir}/metadata.txt"

mkdir -p "${result_dir}"

{
  echo "run_id=${run_id}"
  echo "scenario=${scenario}"
  echo "git_commit=$(git -C "${loadtest_dir}/.." rev-parse HEAD)"
  echo "git_branch=$(git -C "${loadtest_dir}/.." branch --show-current)"
  echo "started_at=$(date -Iseconds)"
  echo "base_url=${base_url}"
  echo "base_port=${base_port}"
  echo "threads=${threads}"
  echo "ramp_up=${ramp_up}"
  echo "loops=${loops}"
  echo "start_date=${start_date}"
  echo "end_date=${end_date}"
  echo "initial_cash=${initial_cash}"
  echo "poll_interval_ms=${poll_interval_ms}"
  echo "max_polls=${max_polls}"
  echo "jmeter_version=$(jmeter --version 2>&1 | sed -n 's/.*Apache JMeter \([0-9][0-9.]*\).*/\1/p' | head -1)"
  echo "machine=$(uname -a)"
} > "${metadata_file}"

echo "백테스트 부하 테스트를 시작합니다: ${run_id}"

jmeter -n \
  -t "${loadtest_dir}/backtest-async-performance.jmx" \
  -j "${result_dir}/jmeter.log" \
  -JBASE_URL="${base_url}" \
  -JBASE_PORT="${base_port}" \
  -JUSER_ID="${USER_ID}" \
  -JSTRATEGY_ID="${STRATEGY_ID}" \
  -JSTART_DATE="${start_date}" \
  -JEND_DATE="${end_date}" \
  -JINITIAL_CASH="${initial_cash}" \
  -JTHREADS="${threads}" \
  -JRAMP_UP="${ramp_up}" \
  -JLOOPS="${loops}" \
  -JPOLL_INTERVAL_MS="${poll_interval_ms}" \
  -JMAX_POLLS="${max_polls}" \
  -l "${jtl_file}" \
  -e \
  -o "${report_dir}"

python3 "${script_dir}/summarize_jtl.py" "${jtl_file}" | tee "${result_dir}/summary.md"

{
  echo "finished_at=$(date -Iseconds)"
  echo "summary=${result_dir}/summary.md"
} >> "${metadata_file}"

echo "완료: ${result_dir}"
