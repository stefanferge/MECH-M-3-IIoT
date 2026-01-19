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

try:
    import adafruit_httpserver  # type: ignore
except ImportError:
    adafruit_httpserver = None

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
        # Try to remount RW on CircuitPython
        try:
            import storage  # type: ignore
            storage.remount("/", False)  # False => read/write
        except Exception:
            pass

        self._settings_cache = settings.copy()
        serialized = self._dump_toml(settings)

        # Safer write
        tmp_path = self.filepath + ".tmp"
        try:
            with open(tmp_path, "wb") as f:
                f.write(serialized)
            try:
                os.remove(self.filepath)
            except Exception:
                pass
            os.rename(tmp_path, self.filepath)
        except OSError as exc:
            # Propagate so API can respond with filesystem_readonly
            raise

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
      # Pin kann Zahl (22) oder String ("GP22") sein – beides wird unterstützt
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
    # MinimalWebServer: Nur /status, robustes Routing, explizite Methoden
    class MinimalWebServer:
        def __init__(self, config_manager, network_manager=None, mqtt_client=None):
            self.config_manager = config_manager
            self.network_manager = network_manager
            self.mqtt_client = mqtt_client
            self.server = None
            self._last_error = None

        def start(self):
            if adafruit_httpserver is None or wifi is None:
                raise RuntimeError("adafruit_httpserver oder wifi nicht verfügbar.")
            if self.server is not None:
                return
            import socketpool  # type: ignore
            pool = socketpool.SocketPool(wifi.radio)
            self.server = adafruit_httpserver.Server(pool, "/static", debug=False)

            # Handlers definieren
            def status_handler(request):
                tm = getattr(time, "gmtime", time.localtime)()
                y, m, d, hh, mm, ss, *_ = tm
                iso = f"{y:04d}-{m:02d}-{d:02d}T{hh:02d}:{mm:02d}:{ss:02d}Z"
                device_id = settings.get("device_id", "unknown")
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
                return adafruit_httpserver.Response(request, body=body, content_type="application/json")

            def api_get_config(request):
                # Use current in-memory settings instead of reloading from disk
                filtered = {
                    "sensor_pin": settings.get("sensor_pin"),
                    "reading_interval_seconds": settings.get("reading_interval_seconds"),
                    "device_id": settings.get("device_id", "unknown"),
                }
                body = json.dumps(filtered)
                return adafruit_httpserver.Response(request, body=body, content_type="application/json")

            def api_put_config(request):
                try:
                    data = request.json()
                except Exception:
                    return adafruit_httpserver.Response(
                        request,
                        json.dumps({"error": "invalid_json"}),
                        content_type="application/json"
                    )

                allowed = {"sensor_pin", "reading_interval_seconds", "device_id"}
                updates = {k: v for k, v in data.items() if k in allowed}
                if not updates:
                    return adafruit_httpserver.Response(
                        request,
                        json.dumps({"error": "no_valid_keys"}),
                        content_type="application/json"
                    )

                # Normalize some types
                if "reading_interval_seconds" in updates:
                    try:
                        updates["reading_interval_seconds"] = float(updates["reading_interval_seconds"])
                    except Exception:
                        return adafruit_httpserver.Response(
                            request,
                            json.dumps({"error": "invalid_reading_interval_seconds"}),
                            content_type="application/json",
                            status="400"
                        )

                # Update in-memory so it takes effect immediately
                for k, v in updates.items():
                    settings[k] = v

                # Try to persist; if FS is read-only, keep in-memory only
                try:
                    self.config_manager.save_settings(settings)
                    return adafruit_httpserver.Response(
                        request,
                        json.dumps({"status": "accepted", "persisted": True, "rebooting": True}),
                        content_type="application/json"
                    )
                except OSError as exc:
                    err = getattr(exc, "errno", None)
                    if err is None and exc.args:
                        try:
                            err = int(exc.args[0])
                        except Exception:
                            err = None
                    readonly = (err == 30) or ("read-only" in str(exc).lower())
                    if readonly:
                        return adafruit_httpserver.Response(
                            request,
                            json.dumps({
                                "status": "accepted",
                                "persisted": False,
                                "rebooting": False,
                                "in_memory": True,
                                "error": "filesystem_readonly"
                            }),
                            content_type="application/json"
                        )
                    return adafruit_httpserver.Response(
                        request,
                        json.dumps({"error": str(exc), "persisted": False}),
                        content_type="application/json",
                        status="500"
                    )
                except Exception as exc:
                    return adafruit_httpserver.Response(
                        request,
                        json.dumps({"error": str(exc)}),
                        content_type="application/json",
                        status="500"
                    )

            def fs_status_handler(request):
                info = {}
                # readonly flag
                try:
                    import storage  # type: ignore
                    m = storage.getmount("/")
                    info["readonly"] = getattr(m, "readonly", None)
                except Exception:
                    info["readonly"] = "unknown"
                # boot_out.txt may indicate safe mode reason
                try:
                    boot_out = None
                    if "boot_out.txt" in os.listdir("/"):
                        with open("/boot_out.txt", "r") as f:
                            boot_out = f.read()
                    info["boot_out"] = boot_out
                except Exception:
                    info["boot_out"] = None
                return adafruit_httpserver.Response(
                    request, body=json.dumps(info), content_type="application/json"
                )

            # Routes REGISTRIEREN, dann starten
            self.server.route("/status", methods=["GET"])(status_handler)
            self.server.route("/config", methods=["GET"])(api_get_config)
            self.server.route("/config", methods=["POST"])(api_put_config)
            self.server.route("/fs", methods=["GET"])(fs_status_handler)

            self.server.start(str(wifi.radio.ipv4_address))
            print("Minimal Webserver läuft auf http://%s:80/status" % wifi.radio.ipv4_address)

        def poll(self):
            if self.server is not None:
                try:
                    self.server.poll()
                except Exception as e:
                    self._last_error = e

        @property
        def last_error(self):
            return self._last_error

    web = MinimalWebServer(cfg, network_manager=net, mqtt_client=mqtt)
    web.start()
  except Exception as e:
    print("Webserver-Fehler:", e)
    web = None

# 7) Hauptschleife – liest in Intervallen und gibt am Terminal aus
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

    # Mess-Intervall prüfen (read dynamically from settings)
    now = time.monotonic()
    interval_cur = float(settings.get("reading_interval_seconds", 2))
    if now - last_send >= interval_cur:
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
