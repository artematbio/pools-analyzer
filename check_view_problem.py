#!/usr/bin/env python3
from database_handler import SupabaseHandler

def check_view_problem():
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('🔍 Проверяем view bio_dao_lp_support...')
    
    # Проверяем что показывает view
    result = supabase_handler.client.table('bio_dao_lp_support').select('*').execute()
    
    print(f'Найдено {len(result.data)} записей в view')
    
    # Группируем по токенам для проверки FDV
    tokens = {}
    for record in result.data:
        token = record['token_symbol']
        network = record['network_display'] 
        fdv = record['token_fdv_usd']
        timestamp = record['snapshot_timestamp'][:16]
        
        if token not in tokens:
            tokens[token] = {}
        
        tokens[token][network] = {'fdv': fdv, 'timestamp': timestamp}
    
    print('\n🔍 FDV в view bio_dao_lp_support:')
    problem_found = False
    
    for token, networks in sorted(tokens.items()):
        if len(networks) > 1:  # Токены на нескольких сетях
            print(f'{token}:')
            fdv_values = []
            for network, data in networks.items():
                fdv_val = data['fdv']
                fdv_values.append(fdv_val)
                print(f'  {network}: FDV ${fdv_val:,.0f} ({data["timestamp"]})')
            
            # Проверяем одинаковые ли FDV
            if len(set(fdv_values)) > 1:
                print(f'  ❌ ПРОБЛЕМА: Разные FDV для {token}!')
                problem_found = True
            else:
                print(f'  ✅ OK: Единый FDV для {token}')
            print()
    
    if problem_found:
        print('\n💡 РЕШЕНИЕ: Нужно обновить view bio_dao_lp_support')
        print('View использует старые данные с неправильным FDV')
        
        # Покажем правильную логику
        print('\n📝 Правильная логика view должна быть:')
        print('''
CREATE OR REPLACE VIEW bio_dao_lp_support AS
WITH latest_snapshots AS (
  SELECT 
    token_symbol,
    network,
    pool_name,
    token_fdv_usd,
    target_lp_value_usd,
    our_position_value_usd,
    lp_gap_usd,
    tvl_usd,
    snapshot_timestamp,
    is_bio_pair,
    ROW_NUMBER() OVER (
      PARTITION BY token_symbol, network, pool_name
      ORDER BY snapshot_timestamp DESC  -- Последние данные
    ) as rn
  FROM dao_pool_snapshots 
  WHERE 
    token_fdv_usd > 0 
    AND is_bio_pair = true  -- Только BIO пары
)
SELECT 
  token_symbol,
  CASE 
    WHEN network = 'ethereum' THEN 'Ethereum'
    WHEN network = 'base' THEN 'Base'  
    WHEN network = 'solana' THEN 'Solana'
    ELSE network
  END as network_display,
  pool_name,
  CASE 
    WHEN target_lp_value_usd > our_position_value_usd * 2 THEN 'Need to Create'
    WHEN our_position_value_usd > target_lp_value_usd * 1.5 THEN 'Excessive Liquidity (Large)'
    ELSE 'Optimal Range'
  END as bio_pair_status,
  token_fdv_usd,
  target_lp_value_usd,
  our_position_value_usd,
  lp_gap_usd,
  tvl_usd,
  snapshot_timestamp
FROM latest_snapshots 
WHERE rn = 1  -- Только последние записи
ORDER BY token_symbol, network;
        ''')

if __name__ == '__main__':
    check_view_problem() 