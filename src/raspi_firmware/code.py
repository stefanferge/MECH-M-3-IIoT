# code.py

# ===================================================================
# Haupt-Anwendung für das yourmuesli.at IoT Environmental Monitoring
#
# Autor: Ihr Team
# Datum: 02.09.2025
#
# Hardware: Raspberry Pi Pico W
# Sensor: DHT22 (Temperatur & Luftfeuchtigkeit)
# Software: CircuitPython
# ===================================================================

# ----------- Bibliotheken importieren ----------- 
# Hier werden später alle benötigten CircuitPython-Bibliotheken importiert
# z.B. import board, time, wifi, adafruit_dht, etc.

import json
import os
import time
try:
    from typing import Any  # type: ignore
except ImportError:
    Any = object  # Fallback für CircuitPython ohne 'typing'

try:
    import tomllib as _toml_reader  # Python 3.11+
except ImportError:
    try:  # pragma: no cover - fallback for CPython <3.11
        import tomli as _toml_reader
    except ImportError:  # pragma: no cover - fallback for CircuitPython
        _toml_reader = None

try:
    import tomli_w as _toml_writer  # preferred writer if available
except ImportError:  # pragma: no cover - fallback
    _toml_writer = None

try:
    import microcontroller  # type: ignore
except ImportError:  # pragma: no cover - running off-device
    microcontroller = None

try:
    import board  # type: ignore
except ImportError:  # pragma: no cover - running off-device
    board = None

try:
    import adafruit_dht  # type: ignore
except ImportError:  # pragma: no cover - running off-device
    adafruit_dht = None

try:
    import wifi  # type: ignore
except ImportError:  # pragma: no cover - running off-device
    wifi = None

try:
    import rtc  # type: ignore
except ImportError:  # pragma: no cover - running off-device
    rtc = None

try:
    import adafruit_ntp  # type: ignore
except ImportError:  # pragma: no cover - running off-device
    adafruit_ntp = None

try:
    from adafruit_minimqtt.adafruit_minimqtt import MQTT  # type: ignore
except ImportError:  # pragma: no cover - running off-device
    MQTT = None

# ---------------------------------------------------------------
# Optional: digitalio für Status-LED importieren (wenn verfügbar)
try:
    import digitalio  # type: ignore
except ImportError:  # pragma: no cover - running off-device
    digitalio = None

# ===================================================================
# KLASSE: ConfigManager
# ===================================================================
class ConfigManager:
    """
    Verwaltet das Laden und Speichern der Konfiguration aus der 'settings.toml'.
    """

    def __init__(self, filepath: str):
        """
        Initialisiert den ConfigManager.

        :param filepath: Der Pfad zur Konfigurationsdatei (z.B. "settings.toml").
        """
        # Auf CircuitPython sicherstellen, dass wir vom Root-Pfad lesen
        if not filepath.startswith("/"):
            filepath = "/" + filepath
        self.filepath = filepath
        self._settings_cache: dict[str, Any] | None = None

    def load_settings(self) -> dict:
        """
        Lädt die Einstellungen aus der TOML-Datei.

        :return: Ein Dictionary mit allen geladenen Einstellungen.
        """
        try:
            with open(self.filepath, "rb") as file:
                raw_content = file.read()
        except OSError as exc:
            raise FileNotFoundError(f"Konfigurationsdatei '{self.filepath}' wurde nicht gefunden.") from exc

        if _toml_reader is None:
            settings = self._parse_minimal_toml(raw_content.decode("utf-8"))
        else:
            settings = _toml_reader.loads(raw_content.decode("utf-8"))

        if not isinstance(settings, dict):
            raise ValueError("Ungültiges Format der Konfigurationsdatei.")

        self._settings_cache = settings
        return settings

    def save_settings(self, settings: dict):
        """
        Speichert Änderungen zurück in die TOML-Datei und startet den
        Mikrocontroller neu, um die neuen Einstellungen zu übernehmen.

        :param settings: Das Dictionary mit den zu speichernden Einstellungen.
        """
        self._settings_cache = settings.copy()
        serialized = self._dump_toml(settings)

        with open(self.filepath, "wb") as file:
            file.write(serialized)

        if microcontroller is not None:
            microcontroller.reset()

    def _parse_minimal_toml(self, content: str) -> dict[str, Any]:
        """
        Minimaler TOML-Parser für einfache key=value Konfigurationen.
        Unterstützt Strings, ints, floats und bools.
        """
        result: dict[str, Any] = {}
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, value = (part.strip() for part in line.split("=", 1))
            result[key] = self._convert_value(value)
        return result

    def _convert_value(self, value: str) -> Any:
        """
        Konvertiert den TOML-Stringwert in den passenden Python-Datentyp.
        """
        if value.startswith('"') and value.endswith('"'):
            return value[1:-1]
        if value.startswith("'") and value.endswith("'"):
            return value[1:-1]

        lowered = value.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"

        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _dump_toml(self, settings: dict) -> bytes:
        """
        Serialisiert das Settings-Dict in TOML.
        """
        if _toml_writer is not None:
            return _toml_writer.dumps(settings).encode("utf-8")

        lines: list[str] = []
        for key, value in settings.items():
            lines.append(f"{key} = {self._format_value(value)}")
        lines.append("")  # sorgt für abschließenden Zeilenumbruch
        return "\n".join(lines).encode("utf-8")

    def _format_value(self, value: Any) -> str:
        """
        Formatiert einen Python-Wert in die TOML-Schreibweise.
        """
        if isinstance(value, str):
            escaped = value.replace('"', '\\"')
            return f'"{escaped}"'
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        raise TypeError(f"Der Wert für TOML wird nicht unterstützt: {value!r}")


# ===================================================================
# KLASSE: NetworkManager
# ===================================================================
class NetworkManager:
    """
    Kümmert sich um die Verbindung zum WLAN-Netzwerk.
    """

    def __init__(self, ssid: str, password: str):
        """
        Initialisiert den NetworkManager mit den WLAN-Zugangsdaten.

        :param ssid: Der Name des WLAN-Netzwerks (SSID).
        :param password: Das Passwort für das WLAN-Netzwerk.
        """
        self.ssid = ssid
        self.password = password
        self.max_retries = 5
        self.retry_delay = 2.0
        self._last_error: Exception | None = None
        self._socket_pool: Any | None = None

    def connect(self) -> bool:
        """
        Stellt die Verbindung zum WLAN her. Versucht es bei einem Fehler
        mehrfach, bevor aufgegeben wird.

        :return: True bei erfolgreicher Verbindung, ansonsten False.
        """
        if wifi is None:
            raise RuntimeError("wifi-Modul ist nicht verfügbar. Läuft der Code auf der Pico W?")

        if self.is_connected():
            return True

        for _ in range(self.max_retries):
            try:
                wifi.radio.connect(self.ssid, self.password)
                self._last_error = None
                self._socket_pool = None  # wird lazily erzeugt
                return True
            except Exception as exc:  # pragma: no cover - hardwareabhängig
                self._last_error = exc
                time.sleep(self.retry_delay)
        return False

    def is_connected(self) -> bool:
        """
        Prüft den aktuellen Verbindungsstatus.

        :return: True, wenn eine WLAN-Verbindung besteht, ansonsten False.
        """
        if wifi is None:
            return False
        try:
            return wifi.radio.ipv4_address is not None
        except AttributeError:  # pragma: no cover - falls radio fehlt
            return False

    def get_ip(self) -> str:
        """
        Gibt die aktuell zugewiesene IP-Adresse des Geräts zurück.

        :return: Die IP-Adresse als String (z.B. "192.168.1.100").
        """
        if not self.is_connected():
            return "0.0.0.0"
        return str(wifi.radio.ipv4_address)

    def get_socket_pool(self) -> Any:
        """
        Liefert einen SocketPool für nachfolgende Netzwerkoperationen.
        """
        if not self.is_connected():
            raise RuntimeError("Keine aktive WLAN-Verbindung.")

        if self._socket_pool is None:
            try:
                import socketpool  # type: ignore
            except ImportError as exc:  # pragma: no cover - abhängig von Firmware
                raise RuntimeError("socketpool-Modul ist nicht verfügbar.") from exc
            self._socket_pool = socketpool.SocketPool(wifi.radio)
        return self._socket_pool

    @property
    def last_error(self) -> Exception | None:
        """
        Gibt den zuletzt aufgetretenen Verbindungsfehler zurück (oder None).
        """
        return self._last_error


# ===================================================================
# KLASSE: Sensor
# ===================================================================
class Sensor:
    """
    Kapselt die Logik zum Auslesen des DHT-Sensors (standardmäßig DHT11).
    """

    def __init__(self, pin_number: int | str, sensor_type: str = "DHT11"):
        """
        Initialisiert den Sensor am angegebenen GPIO-Pin.

        :param pin_number: Die Nummer des GPIO-Pins (z.B. 15 für GP15).
        :param sensor_type: Typ des Sensors ("DHT11" oder "DHT22").
        """
        self.pin_number = pin_number
        self.sensor_type = sensor_type.upper()
        self._sensor: Any | None = None
        self._last_error: Exception | None = None
        self._last_read_timestamp: float = 0.0
        self.min_interval = 2.0  # Sekunden zwischen Messungen laut Datasheet

        if adafruit_dht is None or board is None:
            return

        pin = self._resolve_pin(pin_number)
        if pin is None:
            raise ValueError(f"Unbekannter Pin '{pin_number}'.")

        dht_cls = adafruit_dht.DHT11 if self.sensor_type == "DHT11" else adafruit_dht.DHT22
        # Unter CircuitPython ist Bitbanging nicht erlaubt; daher zuerst ohne Parameter instanzieren.
        try:
            self._sensor = dht_cls(pin)  # nutzt PulseIn
        except TypeError:
            # Fallback für sehr alte Bibliotheksversionen, die den param erwarten
            self._sensor = dht_cls(pin, use_pulseio=True)

    def _resolve_pin(self, pin_number: int | str):
        """
        Konvertiert eine Pin-Nummer oder einen Pin-Namen in das board-Modulobjekt.
        """
        if board is None:
            return None
        if isinstance(pin_number, str):
            return getattr(board, pin_number, None)
        attribute = f"GP{pin_number}"
        return getattr(board, attribute, None)

    def read_data(self) -> dict | None:
        """
        Liest Temperatur und Luftfeuchtigkeit vom Sensor.

        :return: Ein Dictionary wie {'temperature': 22.5, 'humidity': 45.8}
                 oder None, falls das Auslesen fehlschlägt.
        """
        if self._sensor is None:
            raise RuntimeError("DHT-Sensor ist nicht initialisiert. Läuft der Code auf der Pico W?")

        # Sicherstellen, dass der Sensor nicht zu häufig gelesen wird.
        elapsed = time.monotonic() - self._last_read_timestamp
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

        for _ in range(3):
            try:
                temperature = self._sensor.temperature
                humidity = self._sensor.humidity
                if temperature is None or humidity is None:
                    raise RuntimeError("Sensor liefert keine gültigen Werte.")

                self._last_error = None
                self._last_read_timestamp = time.monotonic()
                return {
                    "temperature": float(temperature),
                    "humidity": float(humidity),
                }
            except RuntimeError as exc:  # pragma: no cover - hardwareabhängig
                self._last_error = exc
                time.sleep(1.0)
        return None

    @property
    def last_error(self) -> Exception | None:
        """
        Gibt den zuletzt aufgetretenen Fehler beim Sensorauslesen zurück.
        """
        return self._last_error


# ===================================================================
# KLASSE: MqttClient
# ===================================================================
class MqttClient:
    """
    Verwaltet die Kommunikation mit dem zentralen MQTT-Broker.
    """

    def __init__(self, config: dict):
        """
        Initialisiert den MQTT-Client mit den Broker-Details aus der Konfiguration.

        :param config: Ein Dictionary mit den MQTT-Einstellungen.
        """
        self.config = config
        self.broker = config.get("broker_address")
        self.port = int(config.get("broker_port", 1883))
        self.telemetry_topic = config.get("telemetry_topic")
        self.temperature_topic = config.get("temperature_topic") or (
            f"{self.telemetry_topic}/temperature" if self.telemetry_topic else None
        )
        self.humidity_topic = config.get("humidity_topic") or (
            f"{self.telemetry_topic}/humidity" if self.telemetry_topic else None
        )
        self.status_topic = config.get("status_topic")
        self.username = config.get("mqtt_username")
        self.password = config.get("mqtt_password")
        self.client_id = config.get("device_id", "pico-sensor")
        self.keep_alive = int(config.get("mqtt_keepalive", 60))
        self.use_ssl = bool(config.get("mqtt_use_ssl", False))
        self.loop_timeout = float(config.get("mqtt_loop_timeout", 1.0))
        self._mqtt_client: Any | None = None
        self._socket_pool: Any | None = config.get("socket_pool")
        self._last_error: Exception | None = None
        self._status: str = "offline"

    def set_socket_pool(self, socket_pool: Any):
        """
        Hinterlegt einen SocketPool, falls dieser nicht über den NetworkManager geliefert wird.
        """
        self._socket_pool = socket_pool

    def connect(self):
        """
        Verbindet sich mit dem MQTT-Broker und setzt eine "Last Will and Testament"
        Nachricht, die gesendet wird, falls das Gerät unerwartet die Verbindung verliert.
        """
        if MQTT is None:
            raise RuntimeError("adafruit_minimqtt ist nicht verfügbar.")

        pool = self._ensure_socket_pool()
        if pool is None:
            raise RuntimeError("Kein SocketPool verfügbar. Netzwerkverbindung prüfen.")

        if self._mqtt_client is None:
            self._mqtt_client = MQTT(
                broker=self.broker,
                port=self.port,
                username=self.username,
                password=self.password,
                socket_pool=pool,
                client_id=self.client_id,
                keep_alive=self.keep_alive,
                is_ssl=self.use_ssl,
            )
            if self.status_topic:
                offline_payload = self._build_status_payload("offline")
                self._mqtt_client.will_set(self.status_topic, offline_payload, retain=True)

        try:
            self._mqtt_client.connect()
            self._last_error = None
        except Exception as exc:  # pragma: no cover - abhängig von Netzwerk
            self._last_error = exc
            raise

    @staticmethod
    def _iso8601_utc() -> str:
        """
        Liefert einen UTC-Zeitstempel im ISO-8601-Format.
        """
        tm = getattr(time, "gmtime", time.localtime)()
        y, m, d, hh, mm, ss, *_ = tm
        return f"{y:04d}-{m:02d}-{d:02d}T{hh:02d}:{mm:02d}:{ss:02d}Z"

    def publish_telemetry(self, data: dict):
        """
        Sendet Temperatur- und Luftfeuchtigkeitswerte auf getrennte Topics,
        jeweils inklusive Wert, Einheit und Zeitstempel.

        :param data: Das Dictionary mit den Sensordaten.
        """
        if not self.temperature_topic or not self.humidity_topic:
            raise ValueError("Es sind keine Topics für Temperatur und/oder Luftfeuchtigkeit konfiguriert.")
        if self._mqtt_client is None:
            raise RuntimeError("MQTT-Client ist nicht verbunden.")

        try:
            temperature_value = float(data.get("temperature"))
            humidity_value = float(data.get("humidity"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Ungültige Sensordaten für Temperatur oder Luftfeuchtigkeit.") from exc

        timestamp = self._iso8601_utc()
        readings = (
            (self.temperature_topic, temperature_value, "°C"),
            (self.humidity_topic, humidity_value, "%"),
        )

        try:
            for topic, value, unit in readings:
                payload_obj = {
                    "timestamp": timestamp,
                    "device_id": self.client_id,
                    "value": value,
                    "unit": unit,
                }
                payload = json.dumps(payload_obj)
                self._mqtt_client.publish(topic, payload)
        except Exception as exc:  # pragma: no cover - abhängig vom Netzwerk
            self._last_error = exc
            raise

    def _build_status_payload(self, status: str) -> str:
        """
        Baut das Status-Payload als JSON-String auf.
        """
        return json.dumps(
            {
                "timestamp": self._iso8601_utc(),
                "device_id": self.client_id,
                "status": status,
            }
        )

    def publish_status(self, status: str):
        """
        Sendet eine einfache Statusnachricht (z.B. "online", "rebooting")
        an das definierte Status-Topic.

        :param status: Die zu sendende Statusnachricht.
        """
        if not self.status_topic:
            return
        if self._mqtt_client is None:
            raise RuntimeError("MQTT-Client ist nicht verbunden.")
        payload = self._build_status_payload(status)
        try:
            self._mqtt_client.publish(self.status_topic, payload, retain=True)
            self._status = status
        except Exception as exc:  # pragma: no cover - abhängig vom Netzwerk
            self._last_error = exc
            raise

    def loop(self):
        """
        Hält die MQTT-Verbindung aktiv. Muss regelmäßig in der Hauptschleife
        aufgerufen werden.
        """
        if self._mqtt_client is None:
            return
        try:
            self._mqtt_client.loop(self.loop_timeout)
        except Exception as exc:  # pragma: no cover - abhängig vom Netzwerk
            self._last_error = exc
            raise

    def is_connected(self) -> bool:
        """
        Prüft, ob der Client aktuell mit dem MQTT-Broker verbunden ist.
        """
        if self._mqtt_client is None:
            return False
        return getattr(self._mqtt_client, "is_connected", lambda: False)()

    @property
    def last_error(self) -> Exception | None:
        """
        Gibt den zuletzt aufgetretenen MQTT-Fehler zurück.
        """
        return self._last_error

    def _ensure_socket_pool(self) -> Any | None:
        """
        Stellt sicher, dass ein SocketPool für MQTT verfügbar ist.
        """
        if self._socket_pool is not None:
            return self._socket_pool

        if wifi is None:
            return None

        try:
            import socketpool  # type: ignore
        except ImportError:  # pragma: no cover - abhängig von Firmware
            return None

        self._socket_pool = socketpool.SocketPool(wifi.radio)
        return self._socket_pool


# ===================================================================
# KLASSE: WebServer
# ===================================================================
class WebServer:
    """
    Stellt eine einfache HTTP-Schnittstelle zur Fernkonfiguration bereit.
    """

    def __init__(self, config_manager: ConfigManager, network_manager: Any | None = None, mqtt_client: Any | None = None):
        """
        Initialisiert den Webserver.

        :param config_manager: Eine Instanz des ConfigManagers, um Einstellungen
                               zu lesen und zu speichern.
        """
        self.config_manager = config_manager
        self.port = 80
        self._socket_pool: Any | None = None
        self._listener: Any | None = None
        self._last_client: Any | None = None
        self._last_error: Exception | None = None
        self._pending_reset = False
        self.network_manager = network_manager
        self.mqtt_client = mqtt_client

    def start(self):
        """
        Startet den Webserver, sodass er auf Anfragen lauscht.
        """
        if wifi is None:
            raise RuntimeError("wifi-Modul ist nicht verfügbar. Läuft der Code auf der Pico W?")

        if self._listener is not None:
            return

        if self._socket_pool is None:
            try:
                import socketpool  # type: ignore
            except ImportError as exc:  # pragma: no cover - abhängig von Firmware
                raise RuntimeError("socketpool-Modul ist nicht verfügbar.") from exc
            self._socket_pool = socketpool.SocketPool(wifi.radio)

        sock = self._socket_pool.socket(self._socket_pool.AF_INET, self._socket_pool.SOCK_STREAM)
        sock.settimeout(0)
        sock.bind(("0.0.0.0", self.port))
        sock.listen(2)
        self._listener = sock

    def poll(self):
        """
        Verarbeitet eine einzelne anstehende HTTP-Anfrage. Muss in der
        Hauptschleife des Programms aufgerufen werden.
        """
        if self._listener is None:
            return

        try:
            client, _ = self._listener.accept()
        except OSError as exc:
            # Kein Client wartet -> normal in Non-Blocking.
            if getattr(exc, "errno", None) in (11, 110, 9):
                return
            if str(exc) in {"timed out", "EAGAIN"}:
                return
            self._last_error = exc
            return

        try:
            # Kurz auf eingehende Daten warten und bis zum Headerende lesen
            try:
                client.settimeout(1)
            except Exception:
                pass
            buf = bytearray()
            header_end = -1
            for _ in range(50):  # ~1s worst-case bei settimeout
                try:
                    chunk = client.recv(1024)
                except Exception as _:
                    break
                if not chunk:
                    break
                buf.extend(chunk)
                idx = buf.find(b"\r\n\r\n")
                if idx != -1:
                    header_end = idx
                    break

            # Falls kein Headerende gefunden, dennoch versuchen zu parsen
            data = bytes(buf)

            # Content-Length prüfen und ggf. Body nachladen (PUT/POST)
            try:
                header_text = data.decode("utf-8", "ignore")
                first_line = header_text.split("\r\n", 1)[0]
                parts = first_line.split(" ")
                method = parts[0] if len(parts) >= 1 else "GET"
                content_length = 0
                for line in header_text.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        try:
                            content_length = int(line.split(":", 1)[1].strip())
                        except Exception:
                            content_length = 0
                        break
                if header_end != -1 and content_length > 0 and method in ("POST", "PUT"):
                    have = len(data) - (header_end + 4)
                    to_read = content_length - max(0, have)
                    while to_read > 0:
                        try:
                            chunk = client.recv(min(1024, to_read))
                        except Exception:
                            break
                        if not chunk:
                            break
                        buf.extend(chunk)
                        to_read -= len(chunk)
                    data = bytes(buf)
            except Exception:
                pass

            response = self._handle_request(data.decode("utf-8", "ignore"))
            total = len(response)
            sent = 0
            while sent < total:
                try:
                    n = client.send(response[sent:sent+1024])
                except Exception:
                    break
                if not n:
                    break
                sent += n
        except Exception as exc:  # pragma: no cover - hardwareabhängig
            self._last_error = exc
        finally:
            try:
                client.close()
            except Exception:  # pragma: no cover - best effort
                pass
            # optionaler Neustart nach API-Antwort
            if self._pending_reset:
                try:
                    self._pending_reset = False
                    if microcontroller is not None:
                        microcontroller.reset()
                except Exception:
                    pass

    def _handle_request(self, request: str) -> bytes:
        """
        Parst eine einfache HTTP-Anfrage und liefert die Antwort zurück.
        Unterstützt GET und POST auf "/".
        """
        lines = request.split("\r\n")
        if not lines:
            return self._http_response(400, "Bad Request")

        # Robuste Request-Line-Parsing (z. B. "GET /path HTTP/1.1")
        try:
            first_line = lines[0].strip()
            parts = first_line.split()
            if len(parts) < 2:
                return self._http_response(400, "Bad Request")
            method = parts[0]
            path = parts[1]
        except Exception:
            return self._http_response(400, "Bad Request")

        headers: dict[str, str] = {}
        body = ""
        separator_reached = False
        for line in lines[1:]:
            if line == "":
                separator_reached = True
                continue
            if not separator_reached:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            else:
                body += line + "\n"
        body = body.rstrip("\n")

        # REST JSON API
        if path.startswith("/api/"):
            if method == "OPTIONS":
                return self._http_response(204, "", headers=self._cors_headers())
            if path == "/api/config":
                if method == "GET":
                    return self._api_get_config()
                if method == "PUT":
                    return self._api_put_config(body, headers)
                return self._json_error(405, "method_not_allowed", "Method Not Allowed")
            if path == "/api/status":
                if method == "GET":
                    return self._api_get_status()
                return self._json_error(405, "method_not_allowed", "Method Not Allowed")
            return self._json_error(404, "not_found", "Not Found")

        # HTML UI
        if path == "/":
            if method == "GET":
                return self._handle_get_request()
            if method == "POST":
                return self._handle_post_request(body, headers)
            return self._http_response(405, "Method Not Allowed")
        return self._http_response(404, "Not Found")

    def _handle_get_request(self, _request: Any | None = None) -> bytes:
        """
        Erstellt eine HTML-Seite mit den aktuellen Einstellungen.
        """
        try:
            settings = self.config_manager.load_settings()
        except Exception as exc:
            # Fällt zurück auf leere Anzeige statt 500
            settings = {}
        
        rows = []
        for key, value in settings.items():
            escaped_value = (
                str(value)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )
            rows.append(
                f"<label style='display:block;margin:6px 0'>{key}: "
                f"<input type='text' name='{key}' value=\"{escaped_value}\"></label>"
            )
        rows_html = "\n".join(rows) if rows else "<p><em>Keine Einstellungen gefunden.</em></p>"

        html = (
            "<!DOCTYPE html>"
            "<html><head><meta charset='utf-8'><title>IoT Einstellungen</title>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;"
            "margin:20px;max-width:720px}.btn{padding:8px 12px;border:1px solid #ccc;"
            "border-radius:8px;cursor:pointer}</style></head>"
            "<body>"
            "<h1>Geräteeinstellungen</h1>"
            "<form method='POST' enctype='application/x-www-form-urlencoded'>"
            f"{rows_html}"
            "<button class='btn' type='submit'>Speichern &amp; Neustart</button>"
            "</form>"
            "<hr>"
            "<p>Tipp: API-Status unter <code>/api/status</code>, Config lesen unter "
            "<code>/api/config</code>, ändern via <code>PUT /api/config</code> (JSON).</p>"
            "</body></html>"
        )

        return self._http_response(200, html, content_type="text/html")

    def _cors_headers(self) -> dict[str, str]:
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,PUT,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }

    def _api_get_config(self) -> bytes:
        try:
            settings = self.config_manager.load_settings()
        except Exception as exc:
            return self._json_error(500, "internal_error", str(exc))
        body = json.dumps({"config": settings})
        return self._http_response(200, body, content_type="application/json", headers=self._cors_headers())

    def _api_put_config(self, body: str, headers: dict[str, str]) -> bytes:
        ct = headers.get("content-type", "").lower()
        if "application/json" not in ct:
            return self._json_error(415, "unsupported_media_type", "Expected application/json")
        try:
            data = json.loads(body) if body else {}
        except Exception:
            return self._json_error(400, "invalid_json", "Body is not valid JSON")

        if not isinstance(data, dict):
            return self._json_error(400, "invalid_request", "JSON object expected")

        updates = data.get("config") if "config" in data else data
        if not isinstance(updates, dict) or not updates:
            return self._json_error(400, "invalid_request", "No config fields provided")

        try:
            settings = self.config_manager.load_settings().copy()
            settings.update(updates)
            serialized = self.config_manager._dump_toml(settings)
            with open(self.config_manager.filepath, "wb") as f:
                f.write(serialized)
            self._pending_reset = True
        except Exception as exc:
            return self._json_error(500, "internal_error", str(exc))

        body_resp = json.dumps({"status": "accepted", "rebooting": True})
        headers = self._cors_headers()
        return self._http_response(202, body_resp, content_type="application/json", headers=headers)

    def _api_get_status(self) -> bytes:
        tm = getattr(time, "gmtime", time.localtime)()
        y, m, d, hh, mm, ss, *_ = tm
        iso = f"{y:04d}-{m:02d}-{d:02d}T{hh:02d}:{mm:02d}:{ss:02d}Z"

        device_id = "unknown"
        try:
            cfg = self.config_manager.load_settings()
            device_id = str(cfg.get("device_id", "unknown"))
        except Exception:
            pass

        ip = None
        if self.network_manager is not None:
            try:
                ip = self.network_manager.get_ip()
            except Exception:
                ip = None
        status = None
        if self.mqtt_client is not None:
            try:
                status = getattr(self.mqtt_client, "_status", None)
            except Exception:
                status = None
        body = json.dumps({
            "device_id": device_id,
            "timestamp": iso,
            "status": status or "ok",
            "ip": ip,
        })
        return self._http_response(200, body, content_type="application/json", headers=self._cors_headers())

    def _handle_post_request(self, body: str, headers: dict[str, str] | None = None) -> bytes:
        """
        Parst die Formulardaten, speichert sie und leitet zurück zur Startseite.
        """
        headers = headers or {}
        content_type = headers.get("content-type", "")
        if "application/x-www-form-urlencoded" not in content_type:
            return self._http_response(415, "Unsupported Media Type")

        updates = self._parse_form_urlencoded(body)
        if not updates:
            return self._http_response(400, "Keine Daten empfangen.")

        settings = self.config_manager.load_settings().copy()
        settings.update(updates)
        self.config_manager.save_settings(settings)

        # Wenn save_settings nicht zurückkehrt (wegen Reset), passiert das hier nicht.
        return self._http_response(
            303,
            "Einstellungen gespeichert. Gerät wird neu gestartet.",
            headers={"Location": "/"},
        )

    def _parse_form_urlencoded(self, body: str) -> dict:
        """
        Parst eine application/x-www-form-urlencoded Nutzlast.
        """
        result: dict[str, str] = {}
        for pair in body.split("&"):
            if not pair:
                continue
            if "=" in pair:
                key, value = pair.split("=", 1)
            else:
                key, value = pair, ""
            decoded_key = self._url_decode(key)
            decoded_value = self._url_decode(value)
            result[decoded_key] = decoded_value
        return result

    def _url_decode(self, value: str) -> str:
        """
        Dekodiert URL-kodierte Strings (z.B. %20 -> Leerzeichen).
        """
        value = value.replace("+", " ")
        parts: list[str] = []
        i = 0
        while i < len(value):
            if value[i] == "%" and i + 2 < len(value):
                hex_value = value[i + 1 : i + 3]
                try:
                    parts.append(chr(int(hex_value, 16)))
                    i += 3
                    continue
                except ValueError:
                    pass
            parts.append(value[i])
            i += 1
        return "".join(parts)

    def _http_response(self, status_code: int, body: str, *, content_type: str = "text/plain", headers: dict[str, str] | None = None) -> bytes:
        """
        Baut eine einfache HTTP/1.1-Antwort zusammen.
        """
        reason_phrases = {
            200: "OK",
            303: "See Other",
            400: "Bad Request",
            404: "Not Found",
            405: "Method Not Allowed",
            415: "Unsupported Media Type",
            500: "Internal Server Error",
        }
        reason = reason_phrases.get(status_code, "OK")
        header_lines = [
            f"HTTP/1.1 {status_code} {reason}",
            f"Content-Type: {content_type}; charset=utf-8",
            f"Content-Length: {len(body.encode('utf-8'))}",
            "Connection: close",
        ]
        if headers:
            for key, value in headers.items():
                header_lines.append(f"{key}: {value}")
        header_lines.append("")
        response_str = "\r\n".join(header_lines) + "\r\n" + body
        return response_str.encode("utf-8")

    def _json_error(self, status: int, code: str, message: str) -> bytes:
        body = json.dumps({"error": {"code": code, "message": message}})
        headers = self._cors_headers()
        return self._http_response(status, body, content_type="application/json", headers=headers)

    @property
    def last_error(self) -> Exception | None:
        """
        Liefert den zuletzt aufgetretenen Webserver-Fehler.
        """
        return self._last_error


# ===================================================================
# MAIN-LOGIK
# ===================================================================

print("Starte yourmuesli.at IoT-Umgebung…")

# 1) Konfiguration laden (oder Defaults verwenden, falls Datei fehlt)
cfg = ConfigManager("/settings.toml")
try:
    print("settings.toml Path:", cfg.filepath)

    # exists? – CircuitPython-Variante ohne os.path:
    def _exists(p: str) -> bool:
        try:
            # stat wirft OSError, falls Datei fehlt
            os.stat(p)  # type: ignore[attr-defined]
            return True
        except Exception:
            return False

    print("exists?", _exists(cfg.filepath))
    print("cwd:", os.getcwd())
    print("root files:", os.listdir("/"))
except Exception as _dbg:
    print("Debug check failed:", _dbg)

try:
  settings = cfg.load_settings()
except Exception as e:
  print("Hinweis: settings.toml nicht gefunden oder fehlerhaft – verwende Defaults.")
  settings = {
      "wifi_ssid": "",
      "wifi_password": "",
      "broker_address": "",
      "broker_port": 1883,
      "telemetry_topic": "",
      "status_topic": "",
      "mqtt_username": "",
      "mqtt_password": "",
      "mqtt_keepalive": 60,
      "mqtt_use_ssl": False,
      # ⚠️ Pin kann Zahl (22) oder String ("GP22") sein – beides wird unterstützt
      "sensor_pin": 9,          # GP9 ist Default; passe an, falls Kabel an GP22 steckt
      "sensor_type": "DHT11",  # oder "DHT22"
      "reading_interval_seconds": 2,
  }

# 2) Status-LED vorbereiten (falls verfügbar)
led = None
if digitalio is not None and board is not None:
  try:
    led = digitalio.DigitalInOut(board.LED)
    led.direction = digitalio.Direction.OUTPUT
  except Exception:
    led = None

# 3) Optional: WLAN-Verbindung aufbauen, nur wenn SSID gesetzt ist
net = None
if settings.get("wifi_ssid"):
  try:
    net = NetworkManager(settings.get("wifi_ssid", ""), settings.get("wifi_password", ""))
    print("Verbinde mit WLAN…")
    if not net.connect():
      print("WLAN-Verbindung fehlgeschlagen - fahre ohne Netzwerk fort.")
    else:
      print("WLAN OK:", net.get_ip())
      # NTP: Uhr in UTC mit adafruit_ntp setzen (falls Bibliothek vorhanden)
      try:
        if adafruit_ntp is not None and rtc is not None:
          pool = net.get_socket_pool()
          ntp_server = settings.get("ntp_server", "pool.ntp.org")
          ntp_client = adafruit_ntp.NTP(pool, server=ntp_server)
          rtc.RTC().datetime = ntp_client.datetime
          tm = getattr(time, "gmtime", time.localtime)()
          y, m, d, hh, mm, ss, *_ = tm
          print(f"NTP gesetzt: {y:04d}-{m:02d}-{d:02d}T{hh:02d}:{mm:02d}:{ss:02d}Z")
        else:
          print("NTP nicht verfügbar – Bibliothek oder rtc fehlt.")
      except Exception as e:
        print("NTP-Fehler:", e)
  except Exception as e:
    print("WLAN-Init-Fehler:", e)
    net = None
else:
  print("Keine WLAN-SSID konfiguriert – Netzwerk wird übersprungen.")

# 4) Sensor initialisieren
sensor_pin = settings.get("sensor_pin", 9)
sensor_type = settings.get("sensor_type", "DHT11")
sensor = Sensor(sensor_pin, sensor_type)

# 5) Optional: MQTT verbinden, nur wenn Broker-Adresse gesetzt ist
mqtt = None
if settings.get("broker_address"):
  try:
    mqtt_cfg = settings.copy()
    if net is not None:
      mqtt_cfg["socket_pool"] = net.get_socket_pool()
    mqtt = MqttClient(mqtt_cfg)
    mqtt.connect()
    mqtt.publish_status("ok")
    print("MQTT verbunden")
  except Exception as e:
    print("MQTT-Verbindungsfehler:", e)
    mqtt = None
else:
  print("Kein MQTT-Broker konfiguriert – Telemetrie bleibt lokal im Serial-Log.")

# 6) Optional: Webserver starten (nur sinnvoll mit WLAN)
web = None
if net is not None:
  try:
    web = WebServer(cfg, network_manager=net, mqtt_client=mqtt)
    web.start()
    print("Webserver läuft auf Port 80")
  except Exception as e:
    print("Webserver-Fehler:", e)
    web = None

# 7) Hauptschleife – liest in Intervallen und gibt am Terminal aus
interval = float(settings.get("reading_interval_seconds", 2))
last_send = 0.0

while True:
  try:
    # Netzwerk-Dienste aktuell halten
    if mqtt is not None:
      try:
        mqtt.loop()
      except Exception as e:
        print("MQTT loop Fehler:", e)
        try:
          mqtt.publish_status("error")
        except Exception:
          pass
    if web is not None:
      try:
        web.poll()
      except Exception as e:
        print("Webserver poll Fehler:", e)

    # Mess-Intervall prüfen
    now = time.monotonic()
    if now - last_send >= interval:
      data = sensor.read_data()
      if data:
        # Terminal-Ausgabe
        print(f"Temp: {data['temperature']}°C, Humidity: {data['humidity']}%")
        # optional LED blinken
        if led is not None:
          led.value = True
          time.sleep(0.05)
          led.value = False
        # optional an MQTT senden
        if mqtt is not None and settings.get("telemetry_topic"):
          try:
            # Erfolgreiche Messung: Status auf ok setzen, dann senden
            try:
              mqtt.publish_status("ok")
            except Exception:
              pass
            mqtt.publish_telemetry(data)
          except Exception as e:
            print("MQTT publish Fehler:", e)
            try:
              mqtt.publish_status("error")
            except Exception:
              pass
      else:
        # Fehlermeldung aus Sensor-Layer anzeigen
        print("Sensor liefert keine Werte:", sensor.last_error)
        if mqtt is not None:
          try:
            mqtt.publish_status("error")
          except Exception:
            pass
      last_send = now

    # kleine Pause, damit die Schleife CPU schont
    time.sleep(0.05)

  except Exception as e:
    print("Fehler im Hauptloop:", e)
    if led is not None:
      led.value = False
    time.sleep(1.0)
