#!/usr/bin/env bash

set -euo pipefail

strategy_id="${STRATEGY_ID:-11111111-1111-4111-8111-111111111111}"
redis_container="${REDIS_CONTAINER:-sajo-redis}"
redis_password="${REDIS_PASSWORD:-redis}"

redis_cli() {
  docker exec -e REDISCLI_AUTH="${redis_password}" "${redis_container}" redis-cli --no-auth-warning "$@"
}

delete_exact_key() {
  local key="$1"
  redis_cli DEL "${key}" >/dev/null
}

delete_matching_keys() {
  local pattern="$1"
  redis_cli EVAL '
local cursor = "0"
repeat
  local result = redis.call("SCAN", cursor, "MATCH", ARGV[1], "COUNT", 1000)
  cursor = result[1]
  local keys = result[2]
  if #keys > 0 then
    redis.call("DEL", unpack(keys))
  end
until cursor == "0"
return 1
' 0 "${pattern}" >/dev/null
}

delete_exact_key "strategy:evaluation:state:${strategy_id}"
delete_exact_key "strategy:evaluation:entry-price:${strategy_id}"
delete_matching_keys "strategy:evaluation:event:*:${strategy_id}"

echo "테스트 Strategy에 속한 Redis 키만 정리했습니다: ${strategy_id}"
