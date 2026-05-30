#!/bin/bash
# run_5min.sh — DARKFLOW OTC health check cron (every 5 min)
# Handles: Docker Desktop restarts, ws_proxy, cloudflared tunnel

LOG="/tmp/run_5min.log"
PROJECT_DIR="/home/magnumbrokeroficial/darkflow_otc"
WS_LOG="/tmp/ws_proxy_new.log"
FALLBACK_WS_LOG="/tmp/ws_proxy.log"
TUNNEL_ID="b0b1038c-b433-4543-947c-8d51ab4da7bd"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') — $1" >> "$LOG"
}

# ──────────────────────────────────────────────────────
# 1. Wait for Docker to be available
# ──────────────────────────────────────────────────────
DOCKER_ATTEMPTS=0
MAX_DOCKER_ATTEMPTS=12  # 12 × 5s = 60s max wait
while ! docker info > /dev/null 2>&1; do
    DOCKER_ATTEMPTS=$((DOCKER_ATTEMPTS + 1))
    if [ "$DOCKER_ATTEMPTS" -gt "$MAX_DOCKER_ATTEMPTS" ]; then
        log "FATAL: Docker not available after ${MAX_DOCKER_ATTEMPTS} attempts"
        exit 1
    fi
    log "Docker not ready (attempt ${DOCKER_ATTEMPTS}/${MAX_DOCKER_ATTEMPTS}) — waiting 5s"
    sleep 5
done

# ──────────────────────────────────────────────────────
# 2. Ensure docker compose stack is up
# ──────────────────────────────────────────────────────
if ! docker ps --format '{{.Names}}' | grep -q darkflow_api; then
    log "darkflow_api container not running — starting stack"
    cd "$PROJECT_DIR" && docker compose up -d 2>&1 | while IFS= read -r line; do
        log "docker-compose: $line"
    done
    sleep 5  # let containers initialize
    if docker ps --format '{{.Names}}' | grep -q darkflow_api; then
        log "stack started successfully"
    else
        log "ERROR: stack start failed — darkflow_api still not running"
    fi
else
    log "docker stack: UP"
fi

# ──────────────────────────────────────────────────────
# 3. Check ws_proxy by process existence AND log mtime
# ──────────────────────────────────────────────────────
WS_PID=$(pgrep -f "ws_proxy.py" 2>/dev/null | tr '\n' ' ' | sed 's/ $//')
WS_LOG_FILE=""
if [ -f "$WS_LOG" ]; then
    WS_LOG_FILE="$WS_LOG"
elif [ -f "$FALLBACK_WS_LOG" ]; then
    WS_LOG_FILE="$FALLBACK_WS_LOG"
fi

if [ -n "$WS_LOG_FILE" ]; then
    LAST_TICK=$(stat -c %Y "$WS_LOG_FILE" 2>/dev/null || echo 0)
    NOW=$(date +%s)
    IDLE=$((NOW - LAST_TICK))
else
    LAST_TICK=0
    IDLE=99999
fi

NEED_RESTART=false
if [ -z "$WS_PID" ]; then
    log "ws_proxy: DOWN (no process)"
    NEED_RESTART=true
elif [ "$IDLE" -gt 120 ]; then
    log "ws_proxy: STUCK (pid=$WS_PID, idle=${IDLE}s) — restarting"
    NEED_RESTART=true
else
    log "ws_proxy: OK (pid=$WS_PID, idle=${IDLE}s)"
fi

if $NEED_RESTART; then
    pkill -9 -f ws_proxy.py 2>/dev/null || true
    sleep 2
    cd "$PROJECT_DIR"
    PYTHONUNBUFFERED=1 nohup python3 -u scripts/ws_proxy.py > "$WS_LOG" 2>&1 &
    NEW_PID=$!
    sleep 3
    if ps -p "$NEW_PID" > /dev/null 2>&1; then
        log "ws_proxy restarted (new pid=$NEW_PID)"
    else
        log "ERROR: ws_proxy restart failed — check $WS_LOG"
    fi
fi

# ──────────────────────────────────────────────────────
# 4. Check cloudflared tunnel
# ──────────────────────────────────────────────────────
CF_PID=$(pgrep -f "cloudflared tunnel" 2>/dev/null || true)
if [ -z "$CF_PID" ]; then
    log "cloudflared: DOWN — restarting tunnel $TUNNEL_ID"
    nohup cloudflared tunnel run "$TUNNEL_ID" > /tmp/cloudflared.log 2>&1 &
    sleep 3
    NEW_CF=$(pgrep -f "cloudflared tunnel" 2>/dev/null || true)
    if [ -n "$NEW_CF" ]; then
        log "cloudflared restarted (pid=$NEW_CF)"
    else
        log "ERROR: cloudflared restart failed — check /tmp/cloudflared.log"
    fi
else
    log "cloudflared: OK (pid=$CF_PID)"
fi

log "health check complete"
