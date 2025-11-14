#!/bin/bash

# Script de gestion Docker pour Electra EMS

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

function print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

function print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

function print_error() {
    echo -e "${RED}✗ $1${NC}"
}

function print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

# Fonction pour démarrer tous les services
function start_all() {
    print_header "Starting Electra EMS Services"
    docker-compose up -d postgres mosquitto

    echo "Waiting for PostgreSQL to be ready..."
    sleep 5

    docker-compose up -d ems-api

    print_success "All services started"
    echo ""
    print_info "API: http://localhost:8000"
    print_info "API Docs: http://localhost:8000/docs"
    print_info "PgAdmin: http://localhost:5050 (use --profile dev)"
}

# Fonction pour démarrer avec PgAdmin
function start_with_pgadmin() {
    print_header "Starting Electra EMS with PgAdmin"
    docker-compose --profile dev up -d

    print_success "All services started including PgAdmin"
    echo ""
    print_info "API: http://localhost:8000"
    print_info "API Docs: http://localhost:8000/docs"
    print_info "PgAdmin: http://localhost:5050"
    print_info "  Email: admin@electra.com"
    print_info "  Password: admin"
}

# Fonction pour arrêter tous les services
function stop_all() {
    print_header "Stopping Electra EMS Services"
    docker-compose down
    print_success "All services stopped"
}

# Fonction pour arrêter et supprimer les volumes
function clean() {
    print_header "Cleaning Electra EMS (removing volumes)"
    docker-compose down -v
    print_success "All services stopped and volumes removed"
}

# Fonction pour voir les logs
function logs() {
    SERVICE=${1:-ems-api}
    print_header "Showing logs for $SERVICE"
    docker-compose logs -f $SERVICE
}

# Fonction pour exécuter les tests
function run_tests() {
    print_header "Running Test Scenarios"
    docker-compose --profile test up test-runner
    print_success "Tests completed"
}

# Fonction pour exécuter les migrations
function migrate() {
    print_header "Running Database Migrations"
    docker-compose exec ems-api alembic upgrade head
    print_success "Migrations completed"
}

# Fonction pour créer une nouvelle migration
function create_migration() {
    MESSAGE=$1
    if [ -z "$MESSAGE" ]; then
        print_error "Please provide a migration message"
        echo "Usage: $0 create-migration 'migration message'"
        exit 1
    fi

    print_header "Creating Migration: $MESSAGE"
    docker-compose exec ems-api alembic revision --autogenerate -m "$MESSAGE"
    print_success "Migration created"
}

# Fonction pour se connecter à la base de données
function db_shell() {
    print_header "Connecting to PostgreSQL"
    docker-compose exec postgres psql -U electra -d electra_ems
}

# Fonction pour afficher le statut
function status() {
    print_header "Electra EMS Status"
    docker-compose ps
}

# Fonction pour rebuild
function rebuild() {
    print_header "Rebuilding Electra EMS"
    docker-compose down
    docker-compose build --no-cache
    docker-compose up -d
    print_success "Rebuild completed"
}

# Fonction pour afficher l'aide
function show_help() {
    echo "Electra EMS Docker Management Script"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start            - Start all services"
    echo "  start-dev        - Start all services including PgAdmin"
    echo "  stop             - Stop all services"
    echo "  restart          - Restart all services"
    echo "  clean            - Stop and remove all volumes"
    echo "  logs [service]   - Show logs (default: ems-api)"
    echo "  test             - Run test scenarios"
    echo "  migrate          - Run database migrations"
    echo "  create-migration - Create a new migration"
    echo "  db-shell         - Connect to PostgreSQL"
    echo "  status           - Show services status"
    echo "  rebuild          - Rebuild and restart services"
    echo "  help             - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 start"
    echo "  $0 logs postgres"
    echo "  $0 create-migration 'add user table'"
}

# Main script
case "${1:-}" in
    start)
        start_all
        ;;
    start-dev)
        start_with_pgadmin
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        start_all
        ;;
    clean)
        clean
        ;;
    logs)
        logs ${2:-ems-api}
        ;;
    test)
        run_tests
        ;;
    migrate)
        migrate
        ;;
    create-migration)
        create_migration "$2"
        ;;
    db-shell)
        db_shell
        ;;
    status)
        status
        ;;
    rebuild)
        rebuild
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_error "Unknown command: ${1:-}"
        echo ""
        show_help
        exit 1
        ;;
esac
