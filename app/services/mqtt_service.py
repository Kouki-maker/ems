import asyncio
import json
from typing import Callable, Dict, Optional
from datetime import datetime
import paho.mqtt.client as mqtt
from app.config import settings
from app.mqtt.topics import MQTTTopics
from app.mqtt.messages import (
    ChargerTelemetryMessage,
    SessionStartMessage,
    SessionStopMessage,
    SessionUpdateMessage,
    BESSStatusMessage,
    PowerLimitCommand,
    BESSCommandMessage
)
import logging
from concurrent.futures import ThreadPoolExecutor
import threading

logger = logging.getLogger(__name__)


class MQTTService:
    """
    Service MQTT pour la communication avec les équipements
    """

    def __init__(self, station_id: str):
        self.station_id = station_id
        self.client: Optional[mqtt.Client] = None
        self.connected = False

        # Event loop pour les handlers async
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.executor = ThreadPoolExecutor(max_workers=4)

        # Queue pour les messages à traiter
        self.message_queue = asyncio.Queue()

        # Handlers pour les différents types de messages
        self.telemetry_handlers: list[Callable] = []
        self.session_start_handlers: list[Callable] = []
        self.session_stop_handlers: list[Callable] = []
        self.session_update_handlers: list[Callable] = []
        self.bess_status_handlers: list[Callable] = []

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        """Définir l'event loop à utiliser"""
        self.loop = loop
        logger.info("Event loop set for MQTT service")

    def initialize(self):
        """Initialiser le client MQTT"""
        client_id = f"ems_{self.station_id}_{int(datetime.now().timestamp())}"
        self.client = mqtt.Client(client_id=client_id)

        if settings.MQTT_USERNAME and settings.MQTT_PASSWORD:
            self.client.username_pw_set(
                settings.MQTT_USERNAME,
                settings.MQTT_PASSWORD
            )

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        try:
            self.client.connect(
                settings.MQTT_BROKER_HOST,
                settings.MQTT_BROKER_PORT,
                60
            )
            self.client.loop_start()
            logger.info(f"MQTT client initialized for station {self.station_id}")
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def _on_connect(self, client, userdata, flags, rc):
        """Callback lors de la connexion"""
        if rc == 0:
            self.connected = True
            logger.info("Connected to MQTT Broker successfully")
            self._subscribe_to_topics()
        else:
            logger.error(f"Failed to connect to MQTT Broker with code: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """Callback lors de la déconnexion"""
        self.connected = False
        if rc != 0:
            logger.warning("Unexpected MQTT disconnection. Will auto-reconnect")

    def _subscribe_to_topics(self):
        """S'abonner à tous les topics nécessaires"""
        charger_topics = MQTTTopics.get_all_charger_topics(self.station_id)
        for topic in charger_topics:
            self.client.subscribe(topic, qos=1)
            logger.info(f"Subscribed to: {topic}")

        bess_topics = MQTTTopics.get_all_bess_topics(self.station_id)
        for topic in bess_topics:
            self.client.subscribe(topic, qos=1)
            logger.info(f"Subscribed to: {topic}")

    def _on_message(self, client, userdata, msg):
        """Router pour les messages MQTT entrants"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())

            logger.debug(f"Received message on {topic}")

            # Au lieu de créer des tasks, on utilise run_coroutine_threadsafe
            if self.loop and self.loop.is_running():
                # Router vers le bon handler
                if "/telemetry" in topic:
                    asyncio.run_coroutine_threadsafe(
                        self._handle_charger_telemetry(payload),
                        self.loop
                    )
                elif "/session/start" in topic:
                    asyncio.run_coroutine_threadsafe(
                        self._handle_session_start(payload),
                        self.loop
                    )
                elif "/session/stop" in topic:
                    asyncio.run_coroutine_threadsafe(
                        self._handle_session_stop(payload),
                        self.loop
                    )
                elif "/session/update" in topic:
                    asyncio.run_coroutine_threadsafe(
                        self._handle_session_update(payload),
                        self.loop
                    )
                elif "/bess/status" in topic or "/bess/telemetry" in topic:
                    asyncio.run_coroutine_threadsafe(
                        self._handle_bess_status(payload),
                        self.loop
                    )
            else:
                logger.warning("Event loop not available, message not processed")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from topic {msg.topic}: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

    async def _handle_session_update_mqtt(self, message: SessionUpdateMessage):
        """
        Handler pour les mises à jour de session depuis un chargeur
        """
        logger.debug(f"Session update from {message.charger_id}: {message.session_id}")

        try:
            # Vérifier que la session existe
            if message.session_id not in self.load_manager.sessions:
                logger.warning(f"Session {message.session_id} not found in load manager")
                return

            # Mettre à jour la puissance dans le load manager
            new_allocated = await self.update_power(
                session_id=message.session_id,
                consumed_power=message.consumed_power,
                vehicle_max_power=message.vehicle_max_power
            )

            # IMPORTANT: Mettre à jour aussi l'énergie délivrée
            session_in_memory = self.load_manager.sessions[message.session_id]
            session_in_memory.totalEnergy = message.energy_delivered
            session_in_memory.vehicleSoc = message.vehicle_soc

            # Mettre à jour l'énergie dans la DB
            db_session = await self.session_repo.get_by_session_id(message.session_id)
            if db_session:
                db_session.total_energy = message.energy_delivered
                db_session.vehicle_soc = message.vehicle_soc
                await self.db.commit()

            # Si l'allocation a changé significativement, envoyer la nouvelle limite
            if abs(session_in_memory.allocatedPower - new_allocated) > 0.5:
                self.mqtt.publish_power_limit(
                    charger_id=message.charger_id,
                    connector_id=message.connector_id,
                    power_limit=new_allocated
                )
                logger.info(f"Updated power limit for {message.session_id}: {new_allocated:.1f}kW")

            # Log détaillé
            logger.debug(
                f"Session {message.session_id} updated: "
                f"consumed={message.consumed_power:.1f}kW, "
                f"allocated={new_allocated:.1f}kW, "
                f"energy={message.energy_delivered:.2f}kWh, "
                f"soc={message.vehicle_soc:.1f}%"
            )

        except Exception as e:
            logger.error(f"Error handling session update: {e}", exc_info=True)

    async def _handle_charger_telemetry(self, message: ChargerTelemetryMessage):
        """
        Handler pour la télémétrie des chargeurs
        """
        logger.debug(
            f"Telemetry from {message.charger_id}:{message.connector_id} - "
            f"{message.power / 1000:.1f}kW"
        )

        # Si une session est active sur ce connecteur
        if message.session_id and message.session_id in self.load_manager.sessions:
            session = self.load_manager.sessions[message.session_id]

            # Mettre à jour la puissance consommée (convertir W en kW)
            session.consumedPower = message.power / 1000

            # Mettre à jour le SOC si disponible
            if message.vehicle_soc is not None:
                session.vehicleSoc = message.vehicle_soc

            logger.debug(
                f"Session {message.session_id} telemetry updated: "
                f"power={session.consumedPower:.1f}kW, "
                f"soc={session.vehicleSoc:.1f}%"
            )

    async def _handle_session_start(self, payload: dict):
        """Traiter un démarrage de session"""
        try:
            message = SessionStartMessage(**payload)
            for handler in self.session_start_handlers:
                try:
                    await handler(message)
                except Exception as e:
                    logger.error(f"Error in session start handler: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error handling session start: {e}", exc_info=True)

    async def _handle_session_stop(self, payload: dict):
        """Traiter un arrêt de session"""
        try:
            message = SessionStopMessage(**payload)
            for handler in self.session_stop_handlers:
                try:
                    await handler(message)
                except Exception as e:
                    logger.error(f"Error in session stop handler: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error handling session stop: {e}", exc_info=True)

    async def _handle_session_update(self, payload: dict):
        """Traiter une mise à jour de session"""
        try:
            message = SessionUpdateMessage(**payload)
            for handler in self.session_update_handlers:
                try:
                    await handler(message)
                except Exception as e:
                    logger.error(f"Error in session update handler: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error handling session update: {e}", exc_info=True)

    async def _handle_bess_status(self, payload: dict):
        """Traiter un statut BESS"""
        try:
            message = BESSStatusMessage(**payload)
            for handler in self.bess_status_handlers:
                try:
                    await handler(message)
                except Exception as e:
                    logger.error(f"Error in BESS status handler: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error handling BESS status: {e}", exc_info=True)

    # Enregistrement des handlers

    def register_telemetry_handler(self, handler: Callable):
        """Enregistrer un handler pour la télémétrie"""
        self.telemetry_handlers.append(handler)

    def register_session_start_handler(self, handler: Callable):
        """Enregistrer un handler pour les démarrages de session"""
        self.session_start_handlers.append(handler)

    def register_session_stop_handler(self, handler: Callable):
        """Enregistrer un handler pour les arrêts de session"""
        self.session_stop_handlers.append(handler)

    def register_session_update_handler(self, handler: Callable):
        """Enregistrer un handler pour les mises à jour de session"""
        self.session_update_handlers.append(handler)

    def register_bess_status_handler(self, handler: Callable):
        """Enregistrer un handler pour les statuts BESS"""
        self.bess_status_handlers.append(handler)

    # Publication de commandes

    def publish_power_limit(self, charger_id: str, connector_id: int, power_limit: float):
        """Publier une limite de puissance vers un connecteur"""
        if not self.connected:
            logger.error("Cannot publish: MQTT not connected")
            return False

        topic = MQTTTopics.get_charger_power_limit(
            self.station_id,
            charger_id,
            connector_id
        )

        command = PowerLimitCommand(
            timestamp=datetime.utcnow(),
            charger_id=charger_id,
            connector_id=connector_id,
            power_limit=power_limit
        )

        payload = command.json()
        result = self.client.publish(topic, payload, qos=1)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.debug(f"Published power limit {power_limit}kW to {charger_id}:{connector_id}")
            return True
        else:
            logger.error(f"Failed to publish power limit to {topic}")
            return False

    def publish_bess_command(self, command: str, power: float):
        """Publier une commande vers le BESS"""
        if not self.connected:
            logger.error("Cannot publish: MQTT not connected")
            return False

        topic = MQTTTopics.get_bess_command(self.station_id)

        cmd = BESSCommandMessage(
            timestamp=datetime.utcnow(),
            command=command,
            power=power
        )

        payload = cmd.json()
        result = self.client.publish(topic, payload, qos=1)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.debug(f"Published BESS command: {command} {power}kW")
            return True
        else:
            logger.error(f"Failed to publish BESS command to {topic}")
            return False

    def publish_session_start_command(self, charger_id: str, session_id: str,
                                      connector_id: int, vehicle_max_power: float):
        """Publier une commande de démarrage de session vers un chargeur"""
        topic = f"electra/{self.station_id}/charger/{charger_id}/session/start_command"
        logger.info(f"Publishing to topic: {topic}")
        if not self.connected:
            logger.error("Cannot publish: MQTT not connected")
            return False

        topic = f"electra/{self.station_id}/charger/{charger_id}/session/start_command"

        command = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": session_id,
            "connector_id": connector_id,
            "vehicle_max_power": vehicle_max_power
        }

        payload = json.dumps(command)
        result = self.client.publish(topic, payload, qos=1)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"Published session start command to {charger_id}")
            return True
        else:
            logger.error(f"Failed to publish start command")
            return False


    def disconnect(self):
        """Déconnecter proprement le client MQTT"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            logger.info("MQTT client disconnected")


# Instance globale
_mqtt_service: Optional[MQTTService] = None


def get_mqtt_service() -> MQTTService:
    """Obtenir l'instance globale du service MQTT"""
    if _mqtt_service is None:
        raise RuntimeError("MQTT service not initialized")
    return _mqtt_service


def initialize_mqtt_service(station_id: str) -> MQTTService:
    """Initialiser le service MQTT"""
    global _mqtt_service
    _mqtt_service = MQTTService(station_id)
    _mqtt_service.initialize()
    return _mqtt_service
