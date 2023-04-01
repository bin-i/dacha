#!/bin/sh

set -e

. /venv/bin/activate

exec ble2mqtt "$@"
