import os
import glob
import json
import math
import re
import struct
import asyncio
import decky

class Plugin:
    SETTINGS_RANGES = {
        "sensitivity": (1.0, 10.0),
        "deadzone": (50.0, 600.0),
        "dot_size": (8, 22),
        "dot_opacity": (0.3, 1.0),
    }

    def __init__(self):
        self.sensor_info = None
        self.running = False
        self.loop = None
        self.task = None
        self.evdev_fd = -1
        
        self.enabled = False
        self.sensitivity = 5.0
        self.deadzone = 200.0
        self.invert_x = False
        self.invert_y = False
        self.dot_size = 14
        self.dot_color = "#ffffff"
        self.dot_opacity = 0.95
        
        self.baseline_x = None
        self.baseline_y = None
        self.baseline_z = None
        self.calibrating = False
        self.calibration_samples = []
        
        self.smooth_x = 0.0
        self.smooth_y = 0.0
        self.alpha = 0.16
        self.settings_path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
        self.sensor_status = {"status": "starting", "message": None, "sensor": None}

    def find_sensor(self):
        for dev in sorted(glob.glob("/sys/bus/iio/devices/iio:device*")):
            try:
                channels = [
                    os.path.join(dev, f"in_accel_{axis}_raw")
                    for axis in ("x", "y", "z")
                ]
                if all(os.path.isfile(channel) for channel in channels):
                    name_file = os.path.join(dev, "name")
                    name = "accel"
                    if os.path.exists(name_file):
                        with open(name_file, "r") as f:
                            name = f.read().strip()
                    decky.logger.info(f"[Deckamine] Sensor IIO detectado: {name} en {dev}")
                    return {"type": "iio", "path": dev, "name": name}
            except Exception as e:
                decky.logger.error(f"[Deckamine] Error explorando IIO {dev}: {e}")

        for name_path in sorted(glob.glob("/sys/class/input/event*/device/name")):
            try:
                with open(name_path, "r") as f:
                    dname = f.read().strip().lower()
                    if any(token in dname for token in ("motion", "imu", "accel")):
                        event_dir = os.path.basename(os.path.dirname(os.path.dirname(name_path)))
                        ev_path = f"/dev/input/{event_dir}"
                        if os.path.exists(ev_path):
                            decky.logger.info(f"[Deckamine] Sensor Evdev detectado: {dname} en {ev_path}")
                            return {"type": "evdev", "path": ev_path, "name": dname}
            except Exception as e:
                decky.logger.error(f"[Deckamine] Error explorando evdev {name_path}: {e}")

        decky.logger.error("[Deckamine] No se encontró un acelerómetro IIO o evdev compatible")
        return None

    async def _main(self):
        self.loop = asyncio.get_event_loop()
        self._load_settings()
        self.sensor_info = self.find_sensor()
        if self.sensor_info is None:
            await self._set_sensor_status("unavailable", "No se detectó un acelerómetro compatible.")
            return
        decky.logger.info(f"[Deckamine] Iniciando servicio ({self.sensor_info['type']}) en: {self.sensor_info['path']}")
        await self._set_sensor_status("starting", "Esperando las primeras lecturas del acelerómetro.")
        self.running = True
        self.task = self.loop.create_task(self.motion_loop())

    async def _set_sensor_status(self, status, message=None):
        sensor = self.sensor_info["name"] if self.sensor_info else None
        new_status = {"status": status, "message": message, "sensor": sensor}
        if new_status == self.sensor_status:
            return
        self.sensor_status = new_status
        await decky.emit("deckamine_sensor_status", new_status)

    async def get_sensor_status(self) -> dict:
        return self.sensor_status

    def _load_settings(self):
        try:
            with open(self.settings_path, "r") as settings_file:
                settings = json.load(settings_file)
            if not isinstance(settings, dict):
                raise ValueError("El archivo de ajustes debe contener un objeto JSON")
            self._apply_settings(settings)
            decky.logger.info("[Deckamine] Ajustes persistentes cargados")
        except FileNotFoundError:
            decky.logger.info("[Deckamine] No hay ajustes guardados; se usarán los valores predeterminados")
        except (OSError, ValueError, TypeError, KeyError) as e:
            decky.logger.error(f"[Deckamine] No se pudieron cargar los ajustes: {e}")

    def _apply_settings(self, settings):
        updated = self._validate_settings(settings)
        self._assign_settings(updated)

    def _validate_settings(self, settings):
        if not isinstance(settings, dict):
            raise ValueError("Los ajustes deben enviarse como un objeto")

        updated = self.get_settings_sync()
        for key in ("enabled", "invert_x", "invert_y"):
            if key in settings:
                if type(settings[key]) is not bool:
                    raise ValueError(f"{key} debe ser verdadero o falso")
                updated[key] = settings[key]

        for key in ("sensitivity", "deadzone", "dot_opacity"):
            if key in settings:
                value = settings[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{key} debe ser un número")
                value = float(value)
                minimum, maximum = self.SETTINGS_RANGES[key]
                if not math.isfinite(value) or not minimum <= value <= maximum:
                    raise ValueError(f"{key} debe estar entre {minimum} y {maximum}")
                updated[key] = value

        if "dot_size" in settings:
            value = settings["dot_size"]
            minimum, maximum = self.SETTINGS_RANGES["dot_size"]
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"dot_size debe ser un entero entre {minimum} y {maximum}")
            updated["dot_size"] = value

        if "dot_color" in settings:
            value = settings["dot_color"]
            if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError("dot_color debe ser un color hexadecimal de seis dígitos")
            updated["dot_color"] = value.lower()

        return updated

    def _assign_settings(self, updated):
        self.enabled = updated["enabled"]
        self.sensitivity = updated["sensitivity"]
        self.deadzone = updated["deadzone"]
        self.invert_x = updated["invert_x"]
        self.invert_y = updated["invert_y"]
        self.dot_size = updated["dot_size"]
        self.dot_color = updated["dot_color"]
        self.dot_opacity = updated["dot_opacity"]

    def _save_settings(self, settings):
        settings_dir = os.path.dirname(self.settings_path)
        os.makedirs(settings_dir, exist_ok=True)
        temp_path = self.settings_path + ".tmp"
        with open(temp_path, "w") as settings_file:
            json.dump(settings, settings_file)
            settings_file.flush()
            os.fsync(settings_file.fileno())
        os.replace(temp_path, self.settings_path)

    def get_settings_sync(self):
        return {
            "enabled": self.enabled,
            "sensitivity": self.sensitivity,
            "deadzone": self.deadzone,
            "invert_x": self.invert_x,
            "invert_y": self.invert_y,
            "dot_size": self.dot_size,
            "dot_color": self.dot_color,
            "dot_opacity": self.dot_opacity,
        }

    async def _unload(self):
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.evdev_fd >= 0:
            try:
                os.close(self.evdev_fd)
            except Exception:
                pass
            self.evdev_fd = -1
        decky.logger.info("[Deckamine] Servicio detenido exitosamente")

    async def motion_loop(self):
        if self.sensor_info is None:
            await self._set_sensor_status("unavailable", "No se detectó un acelerómetro compatible.")
            return

        is_iio = self.sensor_info["type"] == "iio"
        rx, ry, rz = 0.0, 0.0, 0.0

        raw_x_file = ""
        raw_y_file = ""
        raw_z_file = ""
        event_fmt = "qqHHi"
        event_sz = struct.calcsize(event_fmt)
        last_sensor_error = None
        seen_axes = set()

        if is_iio:
            raw_x_file = os.path.join(self.sensor_info["path"], "in_accel_x_raw")
            raw_y_file = os.path.join(self.sensor_info["path"], "in_accel_y_raw")
            raw_z_file = os.path.join(self.sensor_info["path"], "in_accel_z_raw")
        else:
            try:
                self.evdev_fd = os.open(self.sensor_info["path"], os.O_RDONLY | os.O_NONBLOCK)
            except Exception as e:
                decky.logger.error(f"[Deckamine] Error abriendo evdev {self.sensor_info['path']}: {e}")

        while self.running:
            try:
                if is_iio:
                    channels = (raw_x_file, raw_y_file, raw_z_file)
                    missing = [path for path in channels if not os.path.isfile(path)]
                    if missing:
                        raise OSError(f"Falta un canal del acelerómetro: {missing[0]}")
                    with open(raw_x_file, "r") as fx, open(raw_y_file, "r") as fy, open(raw_z_file, "r") as fz:
                        rx = float(fx.read().strip())
                        ry = float(fy.read().strip())
                        rz = float(fz.read().strip())
                else:
                    if self.evdev_fd < 0:
                        try:
                            self.evdev_fd = os.open(self.sensor_info["path"], os.O_RDONLY | os.O_NONBLOCK)
                            seen_axes.clear()
                        except OSError as e:
                            await self._set_sensor_status("error", f"No se pudo abrir el sensor: {e}")
                            await asyncio.sleep(1.0)
                            continue

                    try:
                        data = os.read(self.evdev_fd, event_sz * 32)
                        if not data:
                            os.close(self.evdev_fd)
                            self.evdev_fd = -1
                            seen_axes.clear()
                            raise OSError("El dispositivo del sensor se desconectó")
                        for offset in range(0, len(data) - event_sz + 1, event_sz):
                            _, _, ev_type, ev_code, ev_val = struct.unpack_from(event_fmt, data, offset)
                            if ev_type == 3:
                                if ev_code == 0:
                                    rx = float(ev_val)
                                    seen_axes.add(0)
                                elif ev_code == 1:
                                    ry = float(ev_val)
                                    seen_axes.add(1)
                                elif ev_code == 2:
                                    rz = float(ev_val)
                                    seen_axes.add(2)
                    except BlockingIOError:
                        pass

                    if not {0, 1, 2}.issubset(seen_axes):
                        await asyncio.sleep(0.033)
                        continue

                await self._set_sensor_status("ready")

                if self.baseline_x is None:
                    self.baseline_x = rx
                    self.baseline_y = ry
                    self.baseline_z = rz
                    decky.logger.info(f"[Deckamine] Postura inicial registrada: X={rx}, Y={ry}, Z={rz}")

                if self.calibrating:
                    self.calibration_samples.append((rx, ry, rz))
                    if len(self.calibration_samples) >= 15:
                        avg_x = sum(s[0] for s in self.calibration_samples) / len(self.calibration_samples)
                        avg_y = sum(s[1] for s in self.calibration_samples) / len(self.calibration_samples)
                        avg_z = sum(s[2] for s in self.calibration_samples) / len(self.calibration_samples)
                        self.baseline_x = avg_x
                        self.baseline_y = avg_y
                        self.baseline_z = avg_z
                        self.smooth_x = 0.0
                        self.smooth_y = 0.0
                        self.calibrating = False
                        self.calibration_samples = []
                        decky.logger.info(f"[Deckamine] Calibrado completado: X={avg_x}, Y={avg_y}, Z={avg_z}")
                        await decky.emit("deckamine_calibrated", {"status": "ok", "x": avg_x, "y": avg_y})

                if self.enabled:
                    dx = rx - self.baseline_x
                    dy = ry - self.baseline_y

                    self.smooth_x = (self.smooth_x * (1.0 - self.alpha)) + (dx * self.alpha)
                    self.smooth_y = (self.smooth_y * (1.0 - self.alpha)) + (dy * self.alpha)

                    val_x = self.smooth_x if abs(self.smooth_x) > self.deadzone else 0.0
                    val_y = self.smooth_y if abs(self.smooth_y) > self.deadzone else 0.0

                    if self.invert_x:
                        val_x = -val_x
                    if self.invert_y:
                        val_y = -val_y

                    scale = (self.sensitivity / 5.0) * (38.0 / 2200.0)
                    offset_x = max(-42.0, min(42.0, val_x * scale))
                    offset_y = max(-42.0, min(42.0, val_y * scale))

                    await decky.emit("deckamine_motion", {
                        "x": round(offset_x, 2),
                        "y": round(offset_y, 2),
                        "raw_x": round(rx, 1),
                        "raw_y": round(ry, 1),
                        "active": True
                    })
                else:
                    await decky.emit("deckamine_motion", {
                        "x": 0.0,
                        "y": 0.0,
                        "raw_x": round(rx, 1),
                        "raw_y": round(ry, 1),
                        "active": False
                    })

                last_sensor_error = None

            except Exception as e:
                error = str(e)
                if error != last_sensor_error:
                    decky.logger.error(f"[Deckamine] Error leyendo el sensor: {error}")
                    last_sensor_error = error
                await self._set_sensor_status("error", f"No se pudo leer el sensor: {error}")
                await decky.emit("deckamine_motion", {
                    "x": 0.0,
                    "y": 0.0,
                    "raw_x": round(rx, 1),
                    "raw_y": round(ry, 1),
                    "active": False,
                })
                if self.calibrating:
                    self.calibrating = False
                    self.calibration_samples = []
                    await decky.emit("deckamine_calibrated", {
                        "status": "error",
                        "message": error,
                    })

                await asyncio.sleep(0.5)

            await asyncio.sleep(0.033)

    async def calibrate(self) -> bool:
        if not self.running or self.sensor_info is None:
            return False
        decky.logger.info("[Deckamine] Iniciando calibracion...")
        self.calibration_samples = []
        self.calibrating = True
        return True

    async def get_settings(self) -> dict:
        return self.get_settings_sync()

    async def set_settings(self, settings: dict) -> bool:
        updated = self._validate_settings(settings)
        try:
            self._save_settings(updated)
        except OSError as e:
            decky.logger.error(f"[Deckamine] No se pudieron guardar los ajustes: {e}")
            raise
        self._assign_settings(updated)
        return True
