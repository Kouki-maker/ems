from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.database.connection import get_db
from app.database.repositories import ChargerRepository, ConnectorRepository, StationRepository
from app.models.charger import ChargerWithConnectors

router = APIRouter(prefix="/chargers", tags=["Chargers"])


@router.get("/{station_id}/{charger_id}", response_model=ChargerWithConnectors)
async def get_charger_with_connectors(
        station_id: str,
        charger_id: str,
        db: AsyncSession = Depends(get_db)
):
    """Get a charger by its id and its connectors"""
    station_repo = StationRepository(db)
    station = await station_repo.get_by_station_id(station_id)

    if not station:
        raise HTTPException(
            status_code=404,
            detail=f"Station {station_id} not found"
        )

    charger_repo = ChargerRepository(db)
    charger = await charger_repo.get_by_charger_id(station.id, charger_id)

    if not charger:
        raise HTTPException(
            status_code=404,
            detail=f"Charger {charger_id} not found in station {station_id}"
        )

    return charger


@router.get("/{station_id}", response_model=List[ChargerWithConnectors])
async def get_all_station_chargers(
        station_id: str,
        db: AsyncSession = Depends(get_db)
):
    """Récupérer tous les chargeurs d'une station avec leurs connecteurs"""
    station_repo = StationRepository(db)
    station = await station_repo.get_by_station_id(station_id)

    if not station:
        raise HTTPException(
            status_code=404,
            detail=f"Station {station_id} not found"
        )

    charger_repo = ChargerRepository(db)
    chargers = await charger_repo.get_all_by_station(station.id)

    return chargers


@router.get("/{charger_id}/utilization")
async def get_charger_utilization(
        charger_id: int,
        db: AsyncSession = Depends(get_db)
):
    """Get rate utilization per charger"""
    connector_repo = ConnectorRepository(db)
    utilization = await connector_repo.get_connector_utilization(charger_id)

    return utilization
