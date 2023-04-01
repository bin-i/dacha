from __future__ import annotations

import typing as tp

import construct

ATC_MiThermometer_struct = construct.Struct(
    "mac" / construct.Array(6, construct.Byte),
    "temperature" / construct.Int16sb,
    "humidity" / construct.Int8ub,
    "battery" / construct.Int8ub,
    "battery_mv" / construct.Int16ub,
    "frame" / construct.Int8ub,
)


def deserialize(data: bytes) -> tp.Dict[str, tp.Any]:
    p_data = ATC_MiThermometer_struct.parse(data)
    return {
        "mac": str(bytes(p_data.mac).hex(":")).upper(),
        "temperature": p_data.temperature,
        "humidity": p_data.humidity,
        "battery": p_data.battery,
        "battery_mv": p_data.battery_mv,
        "frame": p_data.frame,
    }


def get_parsers() -> tp.Dict[str, tp.Callable[[bytes], tp.Dict[str, tp.Any]]]:
    return {"ATC_MiThermometer": deserialize}
