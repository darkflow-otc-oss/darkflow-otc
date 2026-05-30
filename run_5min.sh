#!/bin/bash
LOG="/tmp/run_5min.log"
echo "$(date) - health check" >> "$LOG"

# Verifica se ws_proxy esta vivo E enviando ticks recentemente
LAST_TICK=$(stat -c %Y /tmp/ws_proxy_new.log 2>/dev/null || stat -c %Y /tmp/ws_proxy.log 2>/dev/null || echo 0)
NOW=$(date +%s)
IDLE=$((NOW - LAST_TICK))

if ! pgrep -f "ws_proxy.py" > /dev/null || [ "$IDLE" -gt 120 ]; then
    echo "$(date) - ws_proxy morto ou travado (idle ${IDLE}s) — reiniciando" >> "$LOG"
    pkill -9 -f ws_proxy.py 2>/dev/null || true
    sleep 2
    cd /home/magnumbrokeroficial/darkflow_otc
    PYTHONUNBUFFERED=1 nohup python3 -u scripts/ws_proxy.py > /tmp/ws_proxy_new.log 2>&1 &
fi

if ! docker ps | grep -q darkflow_api; then
    echo "$(date) - API parada — reiniciando" >> "$LOG"
    cd /home/magnumbrokeroficial/darkflow_otc && docker compose up -d
fi

# Verifica se o tunnel cloudflared esta vivo
if ! pgrep -f "cloudflared tunnel" > /dev/null; then
    echo "$(date) - cloudflared morto — reiniciando" >> "$LOG"
    nohup cloudflared tunnel run b0b1038c-b433-4543-947c-8d51ab4da7bd > /tmp/cloudflared.log 2>&1 &
fi
