-- Redis Signal 중복 차단 부하 테스트 전용 Strategy.
-- 단일 종목에 ACTIVE 전략이 정확히 하나만 존재해야 요청 수와 Signal 수를 직접 비교할 수 있다.
INSERT INTO market_strategy.p_strategies (
    id,
    created_at,
    updated_at,
    user_id,
    stock_id,
    stock_code,
    strategy_name,
    buy_condition_price,
    sell_condition_price,
    stop_loss_rate,
    target_return_rate,
    allocated_amount,
    order_amount,
    per_condition,
    pbr_condition,
    roe_condition,
    status,
    activated_at
) VALUES (
    '11111111-1111-4111-8111-111111111111',
    now(),
    now(),
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333333',
    '999999',
    'Redis Lua performance test',
    70000,
    90000,
    5.0000,
    10.0000,
    10000000,
    1000000,
    NULL,
    NULL,
    NULL,
    'ACTIVE',
    now()
)
ON CONFLICT (id) DO UPDATE SET
    updated_at = now(),
    deleted_at = NULL,
    deleted_by = NULL,
    user_id = EXCLUDED.user_id,
    stock_id = EXCLUDED.stock_id,
    stock_code = EXCLUDED.stock_code,
    strategy_name = EXCLUDED.strategy_name,
    buy_condition_price = EXCLUDED.buy_condition_price,
    sell_condition_price = EXCLUDED.sell_condition_price,
    stop_loss_rate = EXCLUDED.stop_loss_rate,
    target_return_rate = EXCLUDED.target_return_rate,
    allocated_amount = EXCLUDED.allocated_amount,
    order_amount = EXCLUDED.order_amount,
    status = 'ACTIVE',
    activated_at = now();

-- 같은 테스트 종목에 다른 ACTIVE 전략이 남아 있으면 요청당 Signal 기대값이 달라진다.
UPDATE market_strategy.p_strategies
SET status = 'INACTIVE', updated_at = now()
WHERE stock_code = '999999'
  AND id <> '11111111-1111-4111-8111-111111111111'
  AND status = 'ACTIVE';
