#!/usr/bin/env bash
# logs.sh — просмотр логов max-bot с фильтрами.

set -euo pipefail

SERVICE="${BOT_SERVICE:-max-bot}"
N="${2:-100}"

show() {
    sudo journalctl -u "$SERVICE" "$@" --no-pager
}

case "${1:-live}" in
    live|-f)
        echo "▶ live: journalctl -u $SERVICE -f -q  (Ctrl+C для выхода)"
        sudo journalctl -u "$SERVICE" -f -q
        ;;

    tail)
        show -n "$N" -q
        ;;

    today)
        show --since today -q
        ;;

    since)
        shift
        if [ -z "${1:-}" ]; then
            echo "Укажи время: ./logs.sh since \"1 hour ago\""
            exit 1
        fi
        show --since "$*" -q
        ;;

    errors)
        show -n "$N" -q | grep -E "⚠|❌|error|Traceback|Exception" || echo "✅ ошибок не найдено"
        ;;

    weather)
        show -n "$N" -q | grep -E "🌤|weather|погода|Nominatim|slug" || echo "нет записей про погоду"
        ;;

    hermes)
        show -n "$N" -q | grep -E "🤖|Hermes|hermes" || echo "нет записей про Hermes"
        ;;

    wishes)
        show -n "$N" -q | grep -E "💬|wish|пожелание|TypeID=1|TypeID=2" || echo "нет записей про пожелания"
        ;;

    morning)
        show -n "$N" -q | grep -E "☀️|утреннее|TypeID=0|daily_worker" || echo "нет записей про утренние"
        ;;

    warnings)
        show -n "$N" -q | grep -E "🔔|warning|алерт|TypeID=3|TypeID=4" || echo "нет записей про warnings"
        ;;

    typeids)
        show -n "$N" -q | grep -E "TypeID=" || echo "нет записей с TypeID"
        ;;

    heartbeats)
        show -n "$N" -q | grep -E "♥" || echo "нет heartbeat"
        ;;

    clear)
        sudo journalctl --rotate
        sudo journalctl --vacuum-time=1s
        echo "✅ логи очищены"
        ;;

    stats)
        echo "─── Размер журнала для $SERVICE ───"
        sudo journalctl -u "$SERVICE" --disk-usage
        echo
        echo "─── Первая запись ───"
        sudo journalctl -u "$SERVICE" -n 1 --reverse -o short-iso --no-pager
        echo
        echo "─── Последняя запись ───"
        sudo journalctl -u "$SERVICE" -n 1 -o short-iso --no-pager
        ;;

    *)
        cat <<EOF
logs.sh — просмотр логов MAX-бота ($SERVICE)

Использование:
  ./logs.sh                  live-режим (Ctrl+C для выхода)
  ./logs.sh tail [N]         последние N строк (по умолчанию 100)
  ./logs.sh today            с начала сегодня
  ./logs.sh since "1 hour ago"
  ./logs.sh since "2026-10-12 06:00"
  ./logs.sh errors [N]       только ⚠ и ❌
  ./logs.sh weather          только про погоду
  ./logs.sh hermes           только Hermes
  ./logs.sh wishes           пожелания / wish_worker
  ./logs.sh morning          утренние рассылки
  ./logs.sh warnings         warnings молчунам
  ./logs.sh typeids          все записи с TypeID=
  ./logs.sh heartbeats       только heartbeat
  ./logs.sh stats            статистика журнала
  ./logs.sh clear            очистить журнал для сервиса

Переменные:
  BOT_SERVICE=max-bot        имя systemd-сервиса (по умолчанию max-bot)

Примеры:
  ./logs.sh since "1 hour ago"
  ./logs.sh since "2026-10-12"
  ./logs.sh errors today
  BOT_SERVICE=max-bot-test ./logs.sh live
EOF
        ;;
esac