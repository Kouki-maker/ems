from fastapi import APIRouter, Depends, Query, HTTPException
from app.api.dependencies import get_session_service
from app.services.session_service_mqtt import SessionServiceMQTT
import logging
import traceback

router = APIRouter(prefix="/station", tags=["Station"])
logger = logging.getLogger(__name__)


@router.get("/status")
async def get_station_status(
        service: SessionServiceMQTT = Depends(get_session_service)
):
    """
    GET /station/status
    Get real-time status of the station
    """
    try:
        logger.info("Getting station status...")

        if service is None:
            logger.error("Service is None")
            raise HTTPException(status_code=500, detail="Service not initialized")

        if service.load_manager is None:
            logger.error("Load manager is None")
            raise HTTPException(status_code=500, detail="Load manager not initialized")

        status = await service.get_station_status()
        logger.info(f"Station status retrieved: {status.get('activeSessions', 0)} active sessions")
        return status

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting station status: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "type": type(e).__name__,
                "traceback": traceback.format_exc()
            }
        )


@router.get("/power/history")
async def get_power_history(
        minutes: int = Query(60, ge=1, le=1440, description="Minutes d'historique"),
        service: SessionServiceMQTT = Depends(get_session_service)
):
    """
    GET /station/power/history
    Get power history
    """
    try:
        history = await service.get_power_history(minutes=minutes)
        return {
            "period_minutes": minutes,
            "data_points": len(history),
            "history": history
        }
    except Exception as e:
        logger.error(f"Error getting power history: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error getting power history: {str(e)}"
        )


@router.get("/debug")
async def debug_station(
        service: SessionServiceMQTT = Depends(get_session_service)
):
    """
    GET /station/debug
    Debug endpoint to check station status
    """
    return {
        "service_initialized": service is not None,
        "load_manager_initialized": service.load_manager is not None if service else False,
        "bess_controller_initialized": service.bess_controller is not None if service else False,
        "mqtt_connected": service.mqtt.connected if service and service.mqtt else False,
        "station_db_id": service.station_db_id if service else None,
        "num_sessions": len(service.load_manager.sessions) if service and service.load_manager else 0
    }
