import os
import glob
import struct
import asyncio
import decky

class Plugin:
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

    def find_sensor(self):
        for dev in sorted(glob.glob("/sys/bus/iio/devices/iio:device*")):
            try:
                raw_x = os.path.join(dev, "in_accel_x_raw")
                if os.path.exists(raw_x):
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
                    if "motion" in dname or "steam deck" in dname:
                        event_dir = os.path.basename(os.path.dirname(os.path.dirname(name_path)))
                        ev_path = f"/dev/input/{event_dir}"
                        if os.path.exists(ev_path):
                            decky.logger.info(f"[Deckamine] Sensor Evdev detectado: {dname} en {ev_path}")
                            return {"type": "evdev", "path": ev_path, "name": dname}
            except Exception as e:
                decky.logger.error(f"[Deckamine] Error explorando evdev {name_path}: {e}")

        return {"type": "iio", "path": "/sys/bus/iio/devices/iio:device0", "name": "fallback"}

    async def _main(self):
        self.loop = asyncio.get_event_loop()
        self.sensor_info = self.find_sensor()
        decky.logger.info(f"[Deckamine] Iniciando servicio ({self.sensor_info['type']}) en: {self.sensor_info['path']}")
        self.running = True
        self.task = self.loop.create_task(self.motion_loop())

    async def _unload(self):
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
        if self.evdev_fd >= 0:
            try:
                os.close(self.evdev_fd)
            except Exception:
                pass
            self.evdev_fd = -1
        decky.logger.info("[Deckamine] Servicio detenido exitosamente")

    async def motion_loop(self):
        is_iio = self.sensor_info["type"] == "iio"
        rx, ry, rz = 0.0, 0.0, 0.0

        raw_x_file = ""
        raw_y_file = ""
        raw_z_file = ""
        event_fmt = "qqHHi"
        event_sz = struct.calcsize(event_fmt)

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
                    if not os.path.exists(raw_x_file):
                        await asyncio.sleep(1.0)
                        continue
                    with open(raw_x_file, "r") as fx, open(raw_y_file, "r") as fy, open(raw_z_file, "r") as fz:
                        rx = float(fx.read().strip())
                        ry = float(fy.read().strip())
                        rz = float(fz.read().strip())
                else:
                    if self.evdev_fd < 0:
                        try:
                            self.evdev_fd = os.open(self.sensor_info["path"], os.O_RDONLY | os.O_NONBLOCK)
                        except Exception:
                            await asyncio.sleep(1.0)
                            continue

                    try:
                        data = os.read(self.evdev_fd, event_sz * 32)
                        for offset in range(0, len(data) - event_sz + 1, event_sz):
                            _, _, ev_type, ev_code, ev_val = struct.unpack_from(event_fmt, data, offset)
                            if ev_type == 3:
                                if ev_code == 0:
                                    rx = float(ev_val)
                                elif ev_code == 1:
                                    ry = float(ev_val)
                                elif ev_code == 2:
                                    rz = float(ev_val)
                    except BlockingIOError:
                        pass

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

            except Exception:
                pass

            await asyncio.sleep(0.033)

    async def calibrate(self) -> bool:
        decky.logger.info("[Deckamine] Iniciando calibracion...")
        self.calibration_samples = []
        self.calibrating = True
        return True

    async def get_settings(self) -> dict:
        return {
            "enabled": self.enabled,
            "sensitivity": self.sensitivity,
            "deadzone": self.deadzone,
            "invert_x": self.invert_x,
            "invert_y": self.invert_y,
            "dot_size": self.dot_size,
            "dot_color": self.dot_color,
            "dot_opacity": self.dot_opacity
        }

    async def set_settings(self, settings: dict) -> bool:
        if "enabled" in settings:
            self.enabled = bool(settings["enabled"])
        if "sensitivity" in settings:
            self.sensitivity = float(settings["sensitivity"])
        if "deadzone" in settings:
            self.deadzone = float(settings["deadzone"])
        if "invert_x" in settings:
            self.invert_x = bool(settings["invert_x"])
        if "invert_y" in settings:
            self.invert_y = bool(settings["invert_y"])
        if "dot_size" in settings:
            self.dot_size = int(settings["dot_size"])
        if "dot_color" in settings:
            self.dot_color = str(settings["dot_color"])
        if "dot_opacity" in settings:
            self.dot_opacity = float(settings["dot_opacity"])
        return True
