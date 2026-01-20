# IIoT Sensor Stack (MQTT → InfluxDB → Grafana)

Dieses Verzeichnis enthält die containerisierte Referenzlösung, die die Sensordaten des Raspberry Pi Pico (oder weiterer MQTT-Knoten) aufnimmt, historisiert und visualisiert. Sie besteht aus:

- **Mosquitto** (MQTT-Broker) – optionaler lokaler Broker; das Standard-Setup lauscht direkt auf dem externen Broker aus `.env`.
- **Telegraf** – leichtgewichtiger Ingest-Service, der MQTT-Messages automatisch nach InfluxDB schreibt.
- **InfluxDB 2.x** – Zeitreihen-Datenbank inklusive Auth, Buckets und Token.
- **Grafana** – vorkonfigurierte Dashboards für Zeitreihen und Sensor-Übersichten.

## 1. Pico/Mikrocontroller vorbereiten

1. Pico per USB verbinden – das Laufwerk `CIRCUITPY` öffnet sich.
2. Die Datei `src/raspi_firmware/settings.toml` auf den Controller kopieren oder dort bearbeiten.
3. Folgende Werte auf Ihre Umgebung anpassen:
   - `wifi_ssid` / `wifi_password`: WLAN-Zugangsdaten des Standortes.
   - `device_id`: eindeutiger Name pro Sensor (wird als Tag in InfluxDB verwendet).
   - `telemetry_topic`: z. B. `iiot/group/<team>/sensor`. Temperatur- und Luftfeuchte werden automatisch als `/temperature` bzw. `/humidity` angehängt.
   - `status_topic`: z. B. `iiot/group/<team>/sensor/status`.
   - `broker_address`: IP-Adresse oder Hostname des Rechners, auf dem diese Docker-Umgebung läuft (z. B. `192.168.1.50`). Port bleibt `1883`.
4. Pico neu starten. Im Web-Interface des Gerätes (IP im lokalen Netzwerk) können die gleichen Felder später ebenfalls gepflegt werden.

**Wichtig:** Für weitere Sensoren einfach eine Kopie der Firmware flashen, `device_id` + Topics anpassen – keine Änderungen an der Server-Seite notwendig.

## 2. Docker-Umgebung konfigurieren

1. Ins Verzeichnis `src/cloud` wechseln.
2. Die vorhandene `.env` anpassen (mindestens `INFLUXDB_TOKEN` ändern).

   Relevante Variablen:
   - `INFLUXDB_*`: Organisation, Bucket, Admin-User/-Passwort, API-Token (wird auch für Grafana & Telegraf genutzt).
   - `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`: Zugangsdaten des zentralen Brokers (ident mit dem Pico).
   - `MQTT_BASE_TOPIC`, `MQTT_STATUS_TOPIC`, `MQTT_*_TOPICS`: Topic-Struktur, die sowohl Mock-Skript als auch Telegraf verwenden.

3. Stack starten:

   ```bash
   docker compose up -d
   ```

   InfluxDB lauscht auf `localhost:8086`, Grafana auf `localhost:3000`. Telegraf verbindet sich über die `.env`-Werte direkt mit dem externen MQTT-Broker; der lokale Mosquitto-Container kann optional mitlaufen, wird jedoch nicht benötigt.

4. Status prüfen:

   ```bash
   docker compose ps
   docker logs iiot-telegraf
   ```

## 3. Dienste nutzen

- **InfluxDB UI**: [http://localhost:8086](http://localhost:8086) – mit den `.env`-Credentials anmelden. Der Bucket `sensor_metrics` (oder Ihr Name) wurde automatisch angelegt.
- **Grafana**: [http://localhost:3000](http://localhost:3000) – Default-Login `admin / admin123` (bitte ändern!). Ein Datasource-Eintrag sowie das Dashboard „IIoT Sensor Overview“ werden automatisch provisioniert.
- **Dashboards**:
  - Zeitreihen-Panels für Temperatur & Luftfeuchtigkeit (Aggregation über alle Geräte, getrennt nach `unit`).
  - Stat-Panel „Sensoren online“ (zählt Geräte mit Status `ok/online` innerhalb der letzten 15 Minuten).
  - Tabelle „Letzte Sensorzustände“ mit Zeitstempel, Device-ID und Statusmeldung.

## 4. Datenfluss & Erweiterbarkeit

1. Sensoren bzw. das Mock-Skript publizieren JSON-Payloads auf `telemetry_topic/temperature`, `telemetry_topic/humidity` und `status_topic` des externen Brokers. Statusmeldungen enthalten weiterhin `timestamp`, `device_id` und `status`, Telegraf verwendet jedoch bewusst den Ankunftszeitpunkt als Messzeit, sodass falschgehende Echtzeituhren keine Panel-Aussetzer verursachen.
2. Telegraf lauscht mit den in `.env` gesetzten Wildcards (`iiot/group/ferge-peter/sensor/+` bzw. `/status`), validiert das JSON und schreibt zwei Measurements in InfluxDB:
   - `sensor_readings`: numerische Messwerte mit Tags `device_id`, `unit`, `topic`.
   - `sensor_status`: Statusmeldungen inkl. `status_code` (1 = online, 0 = rebooting/offline, −1 = error).
3. Grafana liest direkt via Flux-Queries auf den Bucket. Neue Sensoren erscheinen automatisch, sobald ihr `device_id` Daten publiziert.

### Weitere Sensoren hinzufügen
- Nur `device_id`, Topics und (optional) Standort auf dem jeweiligen Sensor anpassen.
- Die MQTT-Wildcards decken automatisch neue Geräte ab. Für komplett andere Topic-Strukturen lediglich die Variablen `MQTT_TELEMETRY_TOPICS` / `MQTT_STATUS_TOPICS` in `.env` anpassen.

## 5. Betrieb & Wartung

- **Volumes** (`docker volume ls`) sichern, um historische Daten zu behalten (`influxdb-data`, `grafana-data`).
- Updates mit `docker compose pull` & `docker compose up -d` einspielen.
- Logs:
  - Telegraf: `docker logs -f iiot-telegraf`
  - InfluxDB: `docker logs -f iiot-influxdb`
  - Grafana: `docker logs -f iiot-grafana`

## 6. Troubleshooting

| Problem | Lösung |
| --- | --- |
| Sensor verbindet sich nicht mit MQTT | Prüfen, ob `broker_address` im Pico `ping`-bar ist und Port 1883 nicht von einer Firewall blockiert wird. |
| Keine Daten in Grafana | InfluxDB-Bucket auswählen, Token prüfen (`docker compose logs telegraf`). |
| Neue Sensoren tauchen nicht im Dashboard auf | Kontrollieren, ob deren Topics vom Wildcard abgedeckt sind, oder `MQTT_*_TOPICS` anpassen. |
| WLAN-Wechsel | Über `settings.toml` oder das Pico-Webinterface neue SSID+Passwort setzen und Gerät neu starten. |

## 7. Demo-Daten simulieren

Falls kein Sensor aktiv ist, lassen sich Testdaten direkt auf dem externen Broker erzeugen. Das Skript `scripts/send_mock_mqtt.sh` liest automatisch die `.env` ein und publiziert Temperatur-, Luftfeuchte- sowie Status-JSONs mit denselben Zugangsdaten wie der Raspberry Pi Pico.

```bash
# Standardmäßig werden 5 Iterationen für zwei Geräte erzeugt (insgesamt 10 Messreihen)
./scripts/send_mock_mqtt.sh

# Beispiel: 20 Iterationen für drei Geräte mit 1 s Abstand
ITERATIONS=20 INTERVAL=1 DEVICES="mock-001 mock-002 mock-003" ./scripts/send_mock_mqtt.sh
```

Parameter (alle optional, via Umgebungsvariablen):
- `MQTT_BASE_TOPIC`, `MQTT_STATUS_TOPIC`: überschreibt die in `.env` gesetzten Topics.
- `DEVICES`: Leerzeichen-separierte Device-IDs (werden nur in den Payloads verwendet).
- `ITERATIONS`: Wie oft pro Lauf Telemetrie- und Statuspakete erzeugt werden.
- `INTERVAL`: Pause zwischen den Iterationen in Sekunden.

Das Skript nutzt `docker run eclipse-mosquitto` und verbindet sich – genau wie der Pico – direkt mit `MQTT_BROKER_HOST`. Dadurch müssen beim Umstieg auf echte Hardware keine Einstellungen geändert werden. Nach dem Ausführen sollten InfluxDB & Grafana sofort Messwerte anzeigen.

Damit lässt sich die komplette Lösung mit wenigen Befehlen reproduzieren und auf einem handelsüblichen Laptop betreiben.
