#!/bin/bash
ASSETS=("BTCUSD_otc" "BCHUSD_otc" "EURUSD_otc" "TRUMPUSD_otc" "USDJPY_otc")
PORTS=(8002 8003 8004 8005 8006)

for i in "${!ASSETS[@]}"; do
    asset="${ASSETS[$i]}"
    port="${PORTS[$i]}"
    profile="/tmp/playwright_profile_${asset}"
    log="/tmp/ws_proxy_${asset}.log"
    mkdir -p "$profile"
    echo "▶️  Iniciando ${asset} (porta ${port})..."
    PYTHONUNBUFFERED=1 nohup python3 scripts/ws_proxy_multi.py \
        --asset "$asset" \
        --profile "$profile" \
        --port "$port" \
        > "$log" 2>&1 &
    echo "   PID: $! | Log: $log | Porta trade: $port"
    sleep 3
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 5 instancias lancadas. AGORA:"
echo "   Cada janela do navegador que abriu esta no ativo padrao (BTC)."
echo "   Selecione MANUALMENTE o ativo correto em CADA janela:"
for asset in "${ASSETS[@]}"; do
    echo "     • ${asset} → clique no dropdown e escolha o par correspondente"
done
echo ""
echo "   Apos selecionar, os perfis salvam a escolha."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Monitorar: tail -f /tmp/ws_proxy_BTCUSD_otc.log"
echo "🛑 Parar todas: pkill -9 -f ws_proxy_multi.py"
