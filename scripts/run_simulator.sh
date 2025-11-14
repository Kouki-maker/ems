#!/bin/bash

# Script pour lancer les simulateurs

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

STATION_ID="${STATION_ID:-ELECTRA_PARIS_15}"
MQTT_BROKER="${MQTT_BROKER:-localhost}"
MQTT_PORT="${MQTT_PORT:-1883}"

function print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

function show_help() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  charger [ID] [mode]    - Start charger simulator"
    echo "  bess [mode]            - Start BESS simulator"
    echo "  all                    - Start all simulators"
    echo "  scenario [N]           - Run test scenario"
    echo ""
    echo "Examples:"
    echo "  $0 charger CP001 auto"
    echo "  $0 bess interactive"
    echo "  $0 all"
}

function start_charger() {
    CHARGER_ID=${1:-CP001}
    MODE=${2:-interactive}

    print_header "Starting Charger Simulator: $CHARGER_ID"

    python simulators/charger_simulator.py \
        --station-id "$STATION_ID" \
        --charger-id "$CHARGER_ID" \
        --broker "$MQTT_BROKER" \
        --port "$MQTT_PORT" \
        --mode "$MODE"
}

function start_bess() {
    MODE=${1:-interactive}

    print_header "Starting BESS Simulator"

    python simulators/bess_simulator.py \
        --station-id "$STATION_ID" \
        --broker "$MQTT_BROKER" \
        --port "$MQTT_PORT" \
        --mode "$MODE"
}

function start_all() {
    print_header "Starting All Simulators"

    # Lancer les simulateurs en arrière-plan
    python simulators/charger_simulator.py \
        --station-id "$STATION_ID" \
        --charger-id "CP001" \
        --broker "$MQTT_BROKER" \
        --port "$MQTT_PORT" \
        --mode auto \
        --duration 600 &

    sleep 2

    python simulators/charger_simulator.py \
        --station-id "$STATION_ID" \
        --charger-id "CP002" \
        --broker "$MQTT_BROKER" \
        --port "$MQTT_PORT" \
        --mode auto \
        --duration 600 &

    sleep 2

    python simulators/bess_simulator.py \
        --station-id "$STATION_ID" \
        --broker "$MQTT_BROKER" \
        --port "$MQTT_PORT" \
        --mode auto \
        --duration 600 &

    echo -e "${GREEN}✓ All simulators started${NC}"
    echo ""
    echo "Press Ctrl+C to stop all simulators"

    wait
}

case "${1:-help}" in
    charger)
        start_charger ${2:-CP001} ${3:-interactive}
        ;;
    bess)
        start_bess ${2:-interactive}
        ;;
    all)
        start_all
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
