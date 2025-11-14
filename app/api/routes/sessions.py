from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.session import (
    SessionCreate,
    SessionCreateResponse,
    SessionStop,
    PowerUpdate,
    PowerUpdateResponse
)
from app.services.session_service import SessionService
from app.api.dependencies import get_session_service
from app.database.connection import get_db
import uuid
import logging

from app.services.session_service_mqtt import SessionServiceMQTT

router = APIRouter(prefix="/sessions", tags=["Sessions"])
logger = logging.getLogger(__name__)


@router.post("/", response_model=SessionCreateResponse)
async def create_session(
        request: SessionCreate,
        service: SessionServiceMQTT = Depends(get_session_service)
):
    session_id = f"session-{uuid.uuid4().hex[:12]}"

    try:
        allocated_power = await service.create_session(
            session_id=session_id,
            charger_id=request.chargerId,
            connector_id=request.connectorId,
            vehicle_max_power=request.vehicleMaxPower
        )

        service.mqtt.publish_session_start_command(
            charger_id=request.chargerId,
            session_id=session_id,
            connector_id=request.connectorId,
            vehicle_max_power=request.vehicleMaxPower
        )

        logger.info(f"Session {session_id} created, command sent to charger")

        return SessionCreateResponse(
            sessionId=session_id,
            allocatedPower=allocated_power
        )

    except Exception as e:
        logger.error(f"Error creating session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{sessionId}/stop")
async def stop_session(
        sessionId: str,
        request: SessionStop,
        service: SessionService = Depends(get_session_service)
):
    """
    POST /sessions/{sessionId}/stop
    Stop charging a session
    """
    success = await service.stop_session(
        session_id=sessionId,
        consumed_energy=request.consumedEnergy
    )

    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Session {sessionId} not found"
        )

    logger.info(f"Session stopped: {sessionId}, energy: {request.consumedEnergy}kWh")

    return {"success": True}


@router.post("/{sessionId}/power-update", response_model=PowerUpdateResponse)
async def update_session_power(
        sessionId: str,
        request: PowerUpdate,
        service: SessionServiceMQTT = Depends(get_session_service)
):
    """
    POST /sessions/{sessionId}/power-update
    Update consumption
    """
    try:
        # Récupérer la session en DB pour avoir l'énergie actuelle
        db_session = await service.session_repo.get_by_session_id(sessionId)
        if not db_session:
            raise HTTPException(status_code=404, detail="Session not found")

        energy_increment = request.consumedPower / 3600  # kWh
        total_energy = db_session.total_energy + energy_increment

        # Calculer le SOC (approximation)
        soc_increment = energy_increment * 1.5
        vehicle_soc = min(100, db_session.vehicle_soc + soc_increment) if db_session.vehicle_soc else 20.0

        new_allocated = await service.update_power_and_energy(
            session_id=sessionId,
            consumed_power=request.consumedPower,
            vehicle_max_power=request.vehicleMaxPower,
            total_energy=total_energy,
            vehicle_soc=vehicle_soc
        )

        return PowerUpdateResponse(newAllocatedPower=new_allocated)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating power for session {sessionId}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{sessionId}")
async def get_session(
        sessionId: str,
        service: SessionService = Depends(get_session_service),
        db: AsyncSession = Depends(get_db)
):
    """
    GET /sessions/{sessionId}
    Get session details
    """
    from app.database.repositories import SessionRepository

    repo = SessionRepository(db)
    session = await repo.get_by_session_id(sessionId)

    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Session {sessionId} not found"
        )

    return {
        "sessionId": session.session_id,
        "chargerId": session.charger.charger_id,
        "connectorId": session.connector.connector_id,
        "status": session.status.value,
        "startTime": session.start_time.isoformat(),
        "vehicleMaxPower": session.vehicle_max_power,
        "allocatedPower": session.allocated_power,
        "consumedPower": session.consumed_power,
        "totalEnergy": session.total_energy
    }


@router.get("/")
async def get_all_sessions(
        service: SessionService = Depends(get_session_service)
):
    """
    GET /sessions
    Get all active sessions
    """
    sessions = service.get_all_sessions()
    return {"sessions": list(sessions.values())}


@router.get("/statistics/summary")
async def get_session_statistics(
        days: int = 7,
        service: SessionService = Depends(get_session_service)
):
    """
    GET /sessions/statistics/summary
    Obtenir les statistiques des sessions
    """
    stats = await service.get_session_statistics(days=days)
    return stats


@router.get("/{sessionId}/details")
async def get_session_details(
        sessionId: str,
        service: SessionService = Depends(get_session_service),
        db: AsyncSession = Depends(get_db)
):
    """
    GET /sessions/{sessionId}/details

    Get all session details (db + memory)
    """
    from app.database.repositories import SessionRepository

    # Données en mémoire
    memory_session = service.load_manager.sessions.get(sessionId)

    # Données en DB
    repo = SessionRepository(db)
    db_session = await repo.get_by_session_id(sessionId)

    result = {
        "session_id": sessionId,
        "in_memory": {
            "exists": memory_session is not None,
            "data": memory_session.dict() if memory_session else None
        },
        "in_database": {
            "exists": db_session is not None,
            "data": {
                "session_id": db_session.session_id,
                "status": db_session.status.value,
                "consumed_power": db_session.consumed_power,
                "allocated_power": db_session.allocated_power,
                "total_energy": db_session.total_energy,
                "vehicle_soc": db_session.vehicle_soc,
                "start_time": db_session.start_time.isoformat(),
            } if db_session else None
        }
    }

    return result
