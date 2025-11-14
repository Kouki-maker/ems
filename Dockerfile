FROM python:3.11-slim

# Variables d'environnement
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# Installer les dépendances système nécessaires
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copier les requirements et installer les dépendances Python
COPY requirements.txt .

# Installer les dépendances avec verbose pour debug
RUN echo "Installing Python dependencies..." && \
    pip install --upgrade pip && \
    pip install -r requirements.txt && \
    echo "Verifying installations..." && \
    python -c "import alembic; print(f'✓ Alembic {alembic.__version__} installed')" && \
    python -c "import sqlalchemy; print(f'✓ SQLAlchemy {sqlalchemy.__version__} installed')" && \
    python -c "import fastapi; print(f'✓ FastAPI {fastapi.__version__} installed')"

# Copier le code de l'application
COPY ./app ./app
COPY ./scenarios ./scenarios
COPY ./scripts ./scripts
COPY ./alembic ./alembic
COPY ./alembic.ini ./alembic.ini

# Créer les __init__.py manquants si nécessaire
RUN touch /app/alembic/__init__.py && \
    mkdir -p /app/alembic/versions && \
    touch /app/alembic/versions/__init__.py

# Créer les dossiers nécessaires
RUN mkdir -p /app/test_results /app/logs

# Rendre les scripts exécutables
RUN chmod +x ./scripts/*.sh 2>/dev/null || true
RUN chmod +x ./scripts/*.py 2>/dev/null || true

# Exposer le port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Commande par défaut
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
