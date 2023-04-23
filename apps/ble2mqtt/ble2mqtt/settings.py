from __future__ import annotations

import pathlib
import typing as tp

import yaml


class Sensor:
    def __init__(self, **kwargs) -> None:
        self.mac: str = kwargs["mac"]
        self.schema: str = kwargs["schema"]
        self.location: str = kwargs.get("location", "unknown")
        self.device_type: str = kwargs["device_type"]
        self.death_time_sec: tp.Optional[int] = kwargs.get(
            "death_time_sec",
            None,
        )


class Settings:
    def __init__(self, config: pathlib.Path) -> None:
        with open(config) as f:
            settings = yaml.safe_load(f)
        self.devices = [Sensor(**sensor_data) for sensor_data in settings["sensors"]]
        self.frequency_sec = settings.get("frequency_sec", 5)
        self.death_time_sec = settings.get("death_time_sec", 5)
        self.mqtt_gate = settings.get("mqtt_gate", "smartdachapc")
        self.mqtt_prefix = settings.get("mqtt_prefix", "ble2mqtt")
