#!/usr/bin/env bash

set -euo pipefail

BROKER_CONTAINER=${BROKER_CONTAINER:-iiot-mosquitto}
BASE_TOPIC=${BASE_TOPIC:-iiot}
ITERATIONS=${ITERATIONS:-5}
INTERVAL=${INTERVAL:-2}
DEVICES=(${DEVICES:-device-001 device-002})

if ! docker ps --format '{{.Names}}' | grep -q "^${BROKER_CONTAINER}$"; then
  echo "Broker container \"${BROKER_CONTAINER}\" is not running." >&2
  exit 1
fi

rand_float() {
  local min=$1
  local max=$2
  awk -v seed="$RANDOM" -v min="$min" -v max="$max" 'BEGIN{srand(seed); printf "%.2f", min + rand() * (max - min)}'
}

publish() {
  local topic=$1
  local payload=$2
  docker exec "${BROKER_CONTAINER}" mosquitto_pub -h localhost -t "${topic}" -m "${payload}"
}

unit_temp=$'\u00B0C'
unit_humidity="%"
status_cycle=(online ok online rebooting online)

for ((i = 0; i < ITERATIONS; i++)); do
  status=${status_cycle[$((i % ${#status_cycle[@]}))]}
  for device in "${DEVICES[@]}"; do
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    temp_value=$(rand_float 21 27)
    humidity_value=$(rand_float 40 70)

    temp_topic="${BASE_TOPIC}/${device}/sensor/temperature"
    humidity_topic="${BASE_TOPIC}/${device}/sensor/humidity"
    status_topic="${BASE_TOPIC}/${device}/sensor/status"

    printf -v temp_payload '{"timestamp":"%s","device_id":"%s","unit":"%s","value":%s,"topic":"%s"}' \
      "$timestamp" "$device" "$unit_temp" "$temp_value" "$temp_topic"
    printf -v humidity_payload '{"timestamp":"%s","device_id":"%s","unit":"%s","value":%s,"topic":"%s"}' \
      "$timestamp" "$device" "$unit_humidity" "$humidity_value" "$humidity_topic"
    printf -v status_payload '{"timestamp":"%s","device_id":"%s","status":"%s","topic":"%s"}' \
      "$timestamp" "$device" "$status" "$status_topic"

    publish "$temp_topic" "$temp_payload"
    publish "$humidity_topic" "$humidity_payload"
    publish "$status_topic" "$status_payload"
  done
  sleep "${INTERVAL}"
done

echo "Published $((ITERATIONS * ${#DEVICES[@]})) telemetry bursts to ${BROKER_CONTAINER}."
