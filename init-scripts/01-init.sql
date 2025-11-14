-- Script d'initialisation PostgreSQL pour Electra EMS

-- Créer des extensions utiles
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- Créer un utilisateur read-only pour les rapports (optionnel)
CREATE USER electra_readonly WITH PASSWORD 'readonly_password';
GRANT CONNECT ON DATABASE electra_ems TO electra_readonly;
GRANT USAGE ON SCHEMA public TO electra_readonly;

-- Les permissions seront accordées après la création des tables
-- via les migrations Alembic

-- Créer des index supplémentaires pour les performances (optionnel)
-- Ceux-ci peuvent aussi être créés via Alembic

-- Log de l'initialisation
DO $$
BEGIN
    RAISE NOTICE 'Electra EMS Database initialized successfully';
END $$;
