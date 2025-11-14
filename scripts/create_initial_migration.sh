#!/bin/bash

# Script pour créer la migration initiale

set -e

echo "Creating initial database migration..."

# Attendre que le container soit prêt
sleep 2

# Créer la migration initiale
docker-compose exec ems-api alembic revision --autogenerate -m "initial migration"

echo "✓ Initial migration created"
echo ""
echo "To apply the migration, run:"
echo "  make migrate"
echo "  or"
echo "  docker-compose exec ems-api alembic upgrade head"
