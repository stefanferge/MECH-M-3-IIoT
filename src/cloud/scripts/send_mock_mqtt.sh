#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "${ENV_FILE}"
  set +a
fi

BROKER_HOST=${MQTT_BROKER_HOST:-}
BROKER_PORT=${MQTT_BROKER_PORT:-}
if [[ -z "${BROKER_HOST}" && -n "${MQTT_BROKER:-}" ]]; then
  BROKER_HOST="${MQTT_BROKER%:*}"
  BROKER_PORT="${MQTT_BROKER#*:}"
fi
BROKER_HOST=${BROKER_HOST:-localhost}
BROKER_PORT=${BROKER_PORT:-1883}
MQTT_USER=${MQTT_USERNAME:-}
MQTT_PASS=${MQTT_PASSWORD:-}
BASE_TOPIC=${MQTT_BASE_TOPIC:-iiot/group/ferge-peter/sensor}
STATUS_TOPIC=${MQTT_STATUS_TOPIC:-${BASE_TOPIC}/status}
ITERATIONS=${ITERATIONS:-5}
INTERVAL=${INTERVAL:-2}
IFS=' ' read -r -a DEVICE_LIST <<< "${DEVICES:-device-001 device-002}"
MOSQUITTO_IMAGE=${MOSQUITTO_IMAGE:-eclipse-mosquitto:2}

rand_float() {
  local min=$1
  local max=$2
  awk -v seed="$RANDOM" -v min="$min" -v max="$max" 'BEGIN{srand(seed); printf "%.2f", min + rand() * (max - min)}'
}

publish() {
  local topic=$1
  local payload=$2
  local cmd=(docker run --rm "${MOSQUITTO_IMAGE}" mosquitto_pub -h "${BROKER_HOST}" -p "${BROKER_PORT}")
  if [[ -n "${MQTT_USER}" ]]; then
    cmd+=(-u "${MQTT_USER}")
  fi
  if [[ -n "${MQTT_PASS}" ]]; then
    cmd+=(-P "${MQTT_PASS}")
  fi
  cmd+=(-t "${topic}" -m "${payload}")
  "${cmd[@]}"
}

unit_temp=$'\u00B0C'
unit_humidity="%"
status_cycle=(online ok online rebooting online)

for ((i = 0; i < ITERATIONS; i++)); do
  status=${status_cycle[$((i % ${#status_cycle[@]}))]}
  for device in "${DEVICE_LIST[@]}"; do
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    temp_value=$(rand_float 21 27)
    humidity_value=$(rand_float 40 70)

    temp_topic="${BASE_TOPIC}/temperature"
    humidity_topic="${BASE_TOPIC}/humidity"

    printf -v temp_payload '{"timestamp":"%s","device_id":"%s","unit":"%s","value":%s,"topic":"%s"}' \
      "$timestamp" "$device" "$unit_temp" "$temp_value" "$temp_topic"
    printf -v humidity_payload '{"timestamp":"%s","device_id":"%s","unit":"%s","value":%s,"topic":"%s"}' \
      "$timestamp" "$device" "$unit_humidity" "$humidity_value" "$humidity_topic"
    printf -v status_payload '{"timestamp":"%s","device_id":"%s","status":"%s","topic":"%s"}' \
      "$timestamp" "$device" "$status" "$STATUS_TOPIC"

    publish "$temp_topic" "$temp_payload"
    publish "$humidity_topic" "$humidity_payload"
    publish "$STATUS_TOPIC" "$status_payload"
  done
  sleep "${INTERVAL}"
done

echo "Published $((ITERATIONS * ${#DEVICE_LIST[@]})) telemetry bursts to ${BROKER_HOST}:${BROKER_PORT}."
