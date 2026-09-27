import asyncio
import logging
import os
import sys
import tempfile
import types
import unittest
from unittest import mock


decky_stub = types.ModuleType("decky")
decky_stub.DECKY_PLUGIN_SETTINGS_DIR = tempfile.gettempdir()
decky_stub.logger = logging.getLogger("deckamine-test")


async def _emit(*_args, **_kwargs):
    pass


decky_stub.emit = _emit
sys.modules["decky"] = decky_stub
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import Plugin


class PluginSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.plugin = Plugin()
        self.plugin.settings_path = os.path.join(self.temp_dir.name, "settings.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_settings_persist_and_load(self):
        settings = {
            "enabled": True,
            "sensitivity": 8.0,
            "deadzone": 350.0,
            "invert_y": True,
            "dot_size": 18,
            "dot_color": "#00E5FF",
            "dot_opacity": 0.75,
        }
        asyncio.run(self.plugin.set_settings(settings))

        restored = Plugin()
        restored.settings_path = self.plugin.settings_path
        restored._load_settings()

        saved = restored.get_settings_sync()
        self.assertTrue(saved["enabled"])
        self.assertEqual(saved["sensitivity"], 8.0)
        self.assertEqual(saved["deadzone"], 350.0)
        self.assertTrue(saved["invert_y"])
        self.assertEqual(saved["dot_size"], 18)
        self.assertEqual(saved["dot_color"], "#00e5ff")
        self.assertEqual(saved["dot_opacity"], 0.75)

    def test_invalid_values_are_rejected_without_mutating_settings(self):
        original = self.plugin.get_settings_sync()
        invalid_updates = (
            {"enabled": "true"},
            {"sensitivity": float("nan")},
            {"deadzone": 601},
            {"dot_size": 7},
            {"dot_color": "red"},
            {"dot_opacity": 0.2},
        )

        for update in invalid_updates:
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    asyncio.run(self.plugin.set_settings(update))
                self.assertEqual(self.plugin.get_settings_sync(), original)

    def test_partial_settings_leave_other_values_unchanged(self):
        self.plugin._apply_settings({"sensitivity": 7})
        self.assertEqual(self.plugin.sensitivity, 7.0)
        self.assertEqual(self.plugin.deadzone, 200.0)

    def test_failed_save_does_not_apply_settings(self):
        with mock.patch.object(self.plugin, "_save_settings", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                asyncio.run(self.plugin.set_settings({"enabled": True}))
        self.assertFalse(self.plugin.enabled)

    def test_iio_device_requires_all_three_accelerometer_channels(self):
        with mock.patch("main.glob.glob", side_effect=[
            ["/sys/bus/iio/devices/iio:device4"],
            [],
        ]), mock.patch("main.os.path.isfile", side_effect=lambda path: not path.endswith("_z_raw")):
            self.assertIsNone(self.plugin.find_sensor())

    def test_missing_sensor_is_reported_instead_of_using_fallback_path(self):
        with mock.patch("main.glob.glob", return_value=[]):
            self.assertIsNone(self.plugin.find_sensor())
        self.assertFalse(asyncio.run(self.plugin.calibrate()))


if __name__ == "__main__":
    unittest.main()
