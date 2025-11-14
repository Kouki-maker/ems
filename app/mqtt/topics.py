"""
Définition des topics MQTT pour l'EMS
"""


class MQTTTopics:
    """Topics MQTT pour la communication avec les équipements"""

    # Topics Chargeurs (Telemetry - Chargers to EMS)
    CHARGER_TELEMETRY = "electra/{station_id}/charger/{charger_id}/telemetry"
    CHARGER_STATUS = "electra/{station_id}/charger/{charger_id}/status"
    CHARGER_CONNECTOR_STATUS = "electra/{station_id}/charger/{charger_id}/connector/{connector_id}/status"

    # Topics Commandes (Commands - EMS to Chargers)
    CHARGER_COMMAND = "electra/{station_id}/charger/{charger_id}/command"
    CHARGER_POWER_LIMIT = "electra/{station_id}/charger/{charger_id}/connector/{connector_id}/power_limit"

    # Topics Session (Session Events - Chargers to EMS)
    SESSION_START = "electra/{station_id}/charger/{charger_id}/session/start"
    SESSION_STOP = "electra/{station_id}/charger/{charger_id}/session/stop"
    SESSION_UPDATE = "electra/{station_id}/charger/{charger_id}/session/update"

    # Topics BESS (Battery - Bidirectional)
    BESS_STATUS = "electra/{station_id}/bess/status"
    BESS_COMMAND = "electra/{station_id}/bess/command"
    BESS_TELEMETRY = "electra/{station_id}/bess/telemetry"

    # Topics Station (Global)
    STATION_STATUS = "electra/{station_id}/station/status"
    STATION_COMMAND = "electra/{station_id}/station/command"

    @staticmethod
    def get_charger_telemetry(station_id: str, charger_id: str) -> str:
        return f"electra/{station_id}/charger/{charger_id}/telemetry"

    @staticmethod
    def get_charger_command(station_id: str, charger_id: str) -> str:
        return f"electra/{station_id}/charger/{charger_id}/command"

    @staticmethod
    def get_charger_power_limit(station_id: str, charger_id: str, connector_id: int) -> str:
        return f"electra/{station_id}/charger/{charger_id}/connector/{connector_id}/power_limit"

    @staticmethod
    def get_bess_status(station_id: str) -> str:
        return f"electra/{station_id}/bess/status"

    @staticmethod
    def get_bess_command(station_id: str) -> str:
        return f"electra/{station_id}/bess/command"

    @staticmethod
    def get_session_start(station_id: str, charger_id: str) -> str:
        return f"electra/{station_id}/charger/{charger_id}/session/start"

    @staticmethod
    def get_session_update(station_id: str, charger_id: str) -> str:
        return f"electra/{station_id}/charger/{charger_id}/session/update"

    @staticmethod
    def get_all_charger_topics(station_id: str) -> list:
        """Obtenir tous les topics pour s'abonner"""
        return [
            f"electra/{station_id}/charger/+/telemetry",
            f"electra/{station_id}/charger/+/status",
            f"electra/{station_id}/charger/+/connector/+/status",
            f"electra/{station_id}/charger/+/session/start",
            f"electra/{station_id}/charger/+/session/stop",
            f"electra/{station_id}/charger/+/session/update",
        ]

    @staticmethod
    def get_all_bess_topics(station_id: str) -> list:
        """Obtenir tous les topics BESS pour s'abonner"""
        return [
            f"electra/{station_id}/bess/status",
            f"electra/{station_id}/bess/telemetry",
        ]

