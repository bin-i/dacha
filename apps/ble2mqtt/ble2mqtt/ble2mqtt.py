from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pathlib
import typing as tp
from time import time

import paho.mqtt.client as mqtt
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
                self.logger.debug(f"Skip handling: {device=}")
        else:
            self.logger.debug(
                f"Message received: {device=}, {advertisement_data=}",
            )
            for raw_msg in advertisement_data.service_data.values():
                message = self.schemas[device.address](raw_msg)
                message["rssi"] = advertisement_data.rssi
                self.logger.debug(f"Message parsed: {message=}")
                if self._on_message:
                    await self._on_message(message, device.address)
                else:
                    self.logger.warning("No callback setup")


T = tp.TypeVar("T")


class Alive(tp.Generic[T]):
    def __init__(self, timeout: int) -> None:
        self._value: tp.Optional[T] = None
        self._time = time()
        self._timeout = timeout
        self._prev_val: tp.Optional[T] = self._value
        self._fist_call = True

    async def set(self, value: T):
        self._value = value
        self._time = time()

    async def get(self) -> tp.Tuple[tp.Optional[T], bool]:
        result = self._value
        alive_has_changed = False

        if time() - self._time > self._timeout:
            result = None

        if self._fist_call or (self._prev_val is None or result is None) and self._prev_val != result:
            alive_has_changed = True

        self._prev_val = result
        self._fist_call = False
        return result, alive_has_changed


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
        for device in settings.devices:
            self.latest[device.mac] = Alive(
                device.death_time_sec or settings.death_time_sec,
            )

    async def on_message(self, msg: ParsedMessage, mac: str) -> None:
        await self.latest[mac].set(msg)

    async def publish(self) -> None:
        for mac, message in self.latest.items():
            data, has_changed = await message.get()
            if has_changed:
                state = "offline" if data is None else "online"
                self.logger.info(
                    f"Device {mac=} has change availability status: {state=}",
                )
                self.mqtt_client.publish(
                    f"{self.mqtt_prefix}/{mac}/availability",
                    json.dumps({"state": state}).encode(),
                    qos=2,
                    retain=True,
                )
            if data:
                logging.debug(f"{mac=} {data=}")
                self.mqtt_client.publish(
                    f"{self.mqtt_prefix}/{mac}",
                    json.dumps(data).encode(),
                )


async def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--config", type=pathlib.Path, required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("ble2mqtt")
    logger.setLevel(logging.INFO)

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
