from __future__ import annotations

import argparse
import asyncio
import json
import logging.config
import pathlib
import sys
import typing as tp
from time import time

import paho.mqtt.client as mqtt
from ble2mqtt.settings import Sensor
from ble2mqtt.settings import Settings
from ble2mqtt.structs import ATC_MiThermometer
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

ParsedMessage = tp.Dict[str, tp.Any]
Shemas = tp.Dict[str, tp.Callable[[bytes], ParsedMessage]]


class BleHandler:
    def __init__(
        self,
        settings: Settings,
        schemas: Shemas,
        logger: logging.Logger,
    ) -> None:
        self.logger = logger.getChild("BleHandler")
        self.schemas = {device.mac: schemas[device.schema] for device in settings.devices}
        self._on_message: tp.Optional[
            tp.Callable[
                [
                    ParsedMessage,
                    str,
                ],
                tp.Any,
            ]
        ] = None

    def register_on_message_received(
        self,
        callback: tp.Callable[[ParsedMessage, str], tp.Any],
    ):
        self._on_message = callback

    async def handle_on_device_found(
        self,
        device: BLEDevice,
        advertisement_data: AdvertisementData,
    ) -> None:
        if device.address not in self.schemas:
            if device.name and device.name.startswith("ATC_"):
                self.logger.warning(f"Skip handling (LOST?): {device=}")
            else:
                pass
        else:
            self.logger.debug(
                f"Message received: {device=}",
            )
            for raw_msg in advertisement_data.service_data.values():
                message = self.schemas[device.address](raw_msg)
                message["rssi"] = advertisement_data.rssi
                if self._on_message:
                    await self._on_message(message, device.address)
                else:
                    self.logger.warning("No callback setup")


T = tp.TypeVar("T")


class Alive(tp.Generic[T]):
    def __init__(self, timeout: int, logger: logging.Logger) -> None:
        self._logger = logger
        self._value: tp.Optional[T] = None
        self._time = time()
        self._timeout = timeout

    async def set(self, value: T):
        self._value = value
        self._time = time()

    async def get(self) -> tp.Optional[T]:
        self._value

        elapsed = time() - self._time
        if elapsed > self._timeout:
            if self._value is not None:
                self._logger.info(f"too much time: {elapsed} from latest setting, reseting value")
            self._value = None
            self._time = time()

        return self._value


class MqttSender:
    def __init__(
        self,
        settings: Settings,
        mqtt_client: mqtt.Client,
        logger: logging.Logger,
    ) -> None:
        self.logger = logger.getChild("MqttSender")
        self.mqtt_client = mqtt_client
        self.mqtt_prefix = settings.mqtt_prefix
        self.latest: tp.Dict[str, Alive[ParsedMessage]] = {}
        self.devices: tp.Dict[str, Sensor] = {}
        for device in settings.devices:
            self.latest[device.mac] = Alive(
                device.death_time_sec or settings.death_time_sec,
                self.logger.getChild(device.mac),
            )
            self.devices[device.mac] = device

    async def on_message(self, msg: ParsedMessage, mac: str) -> None:
        await self.latest[mac].set(msg)

    async def publish(self) -> None:
        for mac, message in self.latest.items():
            data = await message.get()

            self.mqtt_client.publish(
                f"{self.mqtt_prefix}/{mac}/{self.devices[mac].device_type}/{self.devices[mac].location}/availability",
                json.dumps({"state": "online" if data else "offline"}).encode(),
            )

            if data:
                self.logger.debug(f"send {mac} data")
                self.mqtt_client.publish(
                    f"{self.mqtt_prefix}/{mac}/{self.devices[mac].device_type}/{self.devices[mac].location}",
                    json.dumps(data).encode(),
                )
            else:
                self.logger.debug(f"no data for {mac}")


async def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument(
        "-d",
        "--debug",
        help="Print lots of debugging statements",
        action="store_const",
        dest="loglevel",
        const=logging.DEBUG,
        default=logging.WARNING,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Be verbose",
        action="store_const",
        dest="loglevel",
        const=logging.INFO,
    )
    args = parser.parse_args()

    class _ExcludeErrorsFilter(logging.Filter):
        def filter(self, record):
            """Only lets through log messages with log level below ERROR ."""
            return record.levelno < logging.WARNING

    config = {
        "version": 1,
        "filters": {
            "exclude_errors": {
                "()": _ExcludeErrorsFilter,
            },
        },
        "formatters": {
            # Modify log message format here or replace with your custom formatter class
            "my_formatter": {
                "format": "(%(process)d) %(asctime)s %(name)s (line %(lineno)s) | %(levelname)s %(message)s",
            },
        },
        "handlers": {
            "console_stderr": {
                # Sends log messages with log level ERROR or higher to stderr
                "class": "logging.StreamHandler",
                "level": "WARNING",
                "formatter": "my_formatter",
                "stream": sys.stderr,
            },
            "console_stdout": {
                # Sends log messages with log level lower than ERROR to stdout
                "class": "logging.StreamHandler",
                "level": args.loglevel,
                "formatter": "my_formatter",
                "filters": ["exclude_errors"],
                "stream": sys.stdout,
            },
        },
        "root": {
            # In general, this should be kept at 'NOTSET'.
            # Otherwise it would interfere with the log levels set for each handler.
            "level": "NOTSET",
            "handlers": ["console_stderr", "console_stdout"],
        },
    }

    logging.config.dictConfig(config)
    logger = logging.getLogger("ble2mqtt")

    settings = Settings(pathlib.Path(args.config))

    shemas: Shemas = {}
    shemas.update(ATC_MiThermometer.get_parsers())

    mqtt_client = mqtt.Client()
    mqtt_client.connect(settings.mqtt_gate)

    mqtt_sender = MqttSender(settings, mqtt_client, logger)

    ble_handler = BleHandler(settings, shemas, logger)
    ble_handler.register_on_message_received(mqtt_sender.on_message)

    bleak_scanner = BleakScanner(
        detection_callback=ble_handler.handle_on_device_found,
    )

    async with bleak_scanner:
        while True:
            await asyncio.sleep(settings.frequency_sec)
            await mqtt_sender.publish()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
