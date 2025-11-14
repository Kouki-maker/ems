#!/bin/bash

set -e

echo "========================================="
echo "  Electra EMS - Starting"
echo "========================================="
echo ""

# Vérifier les installations
echo "Verifying Python packages..."
python -c "import alembic; print(f'✓ Alembic {alembic.__version__}')" || {
    echo "✗ Alembic not found, installing..."
    pip install alembic==1.13.0
}

python -c "import sqlalchemy; print(f'✓ SQLAlchemy {sqlalchemy.__version__}')" || {
    echo "✗ SQLAlchemy not found, installing..."
    pip install sqlalchemy==2.0.23
}

python -c "import asyncpg; print(f'✓ asyncpg available')" || {
    echo "✗ asyncpg not found, installing..."
    pip install asyncpg==0.29.0
}

echo ""
echo "Waiting for PostgreSQL to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0

until PGPASSWORD=electra_password psql -h postgres -U electra -d electra_ems -c '\q' 2>/dev/null; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "✗ PostgreSQL not ready after $MAX_RETRIES attempts"
        exit 1
    fi
    echo "  Waiting... (attempt $RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

echo "✓ PostgreSQL is ready"
echo ""

# Vérifier si Alembic est configuré
if [ -f "alembic.ini" ] && [ -d "alembic" ]; then
    echo "Running database migrations..."
    alembic upgrade head && echo "✓ Migrations completed" || {
        echo "⚠ Migration failed, but continuing..."
    }
    echo ""
else
    echo "⚠ Alembic not configured, skipping migrations"
    echo ""
fi

echo "========================================="
echo "  Starting API Server"
echo "  API: http://localhost:8000"
echo "  Docs: http://localhost:8000/docs"
echo "========================================="
echo ""

# Exécuter la commande passée en argument ou uvicorn par défaut
exec "${@:-uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload}"
