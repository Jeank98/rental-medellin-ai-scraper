#!/usr/bin/env bash

set -u

STATE_DIR="${HOME}/.cache/rental-medellin-ai-scraper"
LOW_BATTERY_MARKER="${STATE_DIR}/battery-low-alerted"
GATEWAY_LOG="${STATE_DIR}/gateway.log"

mkdir -p "$STATE_DIR"

check_battery() {
    local battery_json percentage
    battery_json="$(termux-battery-status 2>/dev/null || true)"
    percentage="$(printf '%s' "$battery_json" | python -c \
        'import json, sys; print(json.load(sys.stdin).get("percentage", ""))' \
        2>/dev/null || true)"

    case "$percentage" in
        ''|*[!0-9]*) return 0 ;;
    esac

    if [ "$percentage" -lt 25 ]; then
        if [ ! -e "$LOW_BATTERY_MARKER" ]; then
            termux-notification \
                --id rental-medellin-low-battery \
                --title "Batería baja" \
                --content "La batería está al ${percentage}%. Conecta el teléfono para que el scraper de las 2:00 a. m. pueda ejecutarse." \
                --priority high \
                --sound \
                --vibrate 300,500,300 \
                >/dev/null 2>&1 || true
            touch "$LOW_BATTERY_MARKER"
        fi
    elif [ "$percentage" -ge 30 ]; then
        rm -f "$LOW_BATTERY_MARKER"
    fi
}

keep_gateway_alive() {
    if pgrep -f '[h]ermes gateway run' >/dev/null 2>&1; then
        return 0
    fi

    termux-wake-lock >/dev/null 2>&1 || true
    nohup proot-distro login ubuntu --shared-tmp -- bash -lc \
        'cd /root/rental-medellin-ai-scraper && exec hermes gateway run' \
        >>"$GATEWAY_LOG" 2>&1 &
}

check_battery
keep_gateway_alive
