from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # API
    API_TITLE: str = "Electra EMS API"
    API_VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://electra:electra_password@postgres:5432/electra_ems"
    DATABASE_ECHO: bool = False  # Set to True for SQL query logging

    # MQTT (optionnel)
    MQTT_BROKER_HOST: str = "mosquitto"
    MQTT_BROKER_PORT: int = 1883
    MQTT_USERNAME: Optional[str] = None
    MQTT_PASSWORD: Optional[str] = None

    LOG_LEVEL: str = "INFO"
    # Station Config
    STATION_CONFIG_PATH: str = "station_config.json"

    class Config:
        env_file = ".env"


settings = Settings()
