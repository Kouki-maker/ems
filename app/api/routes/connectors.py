from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.database.connection import get_db
from app.database.repositories import ConnectorRepository, ChargerRepository
from app.models.connector import ConnectorResponse, ConnectorUpdate, ConnectorStatus

router = APIRouter(prefix="/connectors", tags=["Connectors"])


@router.get("/{connector_id}", response_model=ConnectorResponse)
async def get_connector(
        connector_id: int,
        db: AsyncSession = Depends(get_db)
):
    """Récupérer les détails d'un connecteur"""
    repo = ConnectorRepository(db)
    connector = await repo.get_by_id(connector_id)

    if not connector:
        raise HTTPException(
            status_code=404,
            detail=f"Connector {connector_id} not found"
        )

    return connector


@router.get("/charger/{charger_id}", response_model=List[ConnectorResponse])
async def get_charger_connectors(
        charger_id: str,
        db: AsyncSession = Depends(get_db)
):
    """Récupérer tous les connecteurs d'un chargeur"""
    # Récupérer le chargeur
    charger_repo = ChargerRepository(db)
    # Note: Il faudrait avoir le station_id, pour simplifier on suppose qu'on l'a
    # Dans une vraie implémentation, on pourrait passer par l'ID de base de données

    connector_repo = ConnectorRepository(db)
    # Utiliser directement l'ID de BDD du chargeur
    # Cette méthode nécessiterait d'être adaptée selon votre logique

    raise HTTPException(
        status_code=501,
        detail="Use /chargers/{charger_id}/connectors instead"
    )


@router.patch("/{connector_id}", response_model=ConnectorResponse)
async def update_connector(
        connector_id: int,
        update_data: ConnectorUpdate,
        db: AsyncSession = Depends(get_db)
):
    """Update connector"""
    repo = ConnectorRepository(db)

    if update_data.status:
        connector = await repo.update_status(connector_id, update_data.status.value)
    else:
        connector = await repo.get_by_id(connector_id)
        # Appliquer d'autres mises à jour si nécessaire

    if not connector:
        raise HTTPException(
            status_code=404,
            detail=f"Connector {connector_id} not found"
        )

    return connector


@router.get("/station/{station_id}/available", response_model=List[ConnectorResponse])
async def get_available_connectors(
        station_id: str,
        db: AsyncSession = Depends(get_db)
):
    """Get all available connectors"""
    from app.database.repositories import StationRepository

    # Récupérer la station
    station_repo = StationRepository(db)
    station = await station_repo.get_by_station_id(station_id)

    if not station:
        raise HTTPException(
            status_code=404,
            detail=f"Station {station_id} not found"
        )

    connector_repo = ConnectorRepository(db)
    connectors = await connector_repo.get_available_connectors(station.id)

    return connectors
