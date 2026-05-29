#!/bin/bash
# DARKFLOW OTC - Script executado a cada 5 minutos

LOG_FILE="/tmp/run_5min.log"

echo "$(date) - Executando run_5min.sh" >> "$LOG_FILE"

# Verificar ws_proxy e reiniciar se necessario
if ! pgrep -f "ws_proxy.py" > /dev/null; then
    echo "$(date) - ws_proxy parado, reiniciando..." >> "$LOG_FILE"
    cd ~/darkflow_otc && nohup python3 scripts/ws_proxy.py > /tmp/ws_proxy.log 2>&1 &
fi

# Verificar containers
if ! docker ps | grep -q darkflow_api; then
    echo "$(date) - API parada, reiniciando..." >> "$LOG_FILE"
    cd ~/darkflow_otc && docker compose up -d
fi

echo "$(date) - Execucao concluida" >> "$LOG_FILE"
