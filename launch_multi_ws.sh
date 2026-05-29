#!/bin/bash
set -e
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 LANCANDO MULTIPLAS INSTANCIAS DO WS_PROXY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Parar todas as instancias anteriores
pkill -9 -f "ws_proxy" 2>/dev/null || true
sleep 2

ASSETS=(
    "BTCUSD_otc"
    "BCHUSD_otc"
    "ETHUSD_otc"
    "EURUSD_otc"
    "LTCUSD_otc"
)

for asset in "${ASSETS[@]}"; do
    LOG_FILE="/tmp/ws_proxy_${asset}.log"

    echo "▶️  Iniciando ws_proxy para ${asset}..."
    PYTHONUNBUFFERED=1 nohup python3 -u scripts/ws_proxy.py \
        > "$LOG_FILE" 2>&1 &

    echo "   PID: $! | Log: $LOG_FILE"
    sleep 3
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ ${#ASSETS[@]} instancias rodando."
echo "   Para verificar: tail -f /tmp/ws_proxy_*.log"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
