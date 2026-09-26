<p align="center">
  <img src="assets/banner.png" alt="Deckamine Banner" width="100%" />
</p>

# Deckamine 🚗💨

**Vehicle Motion Cues for SteamOS / ROG Ally / Handhelds**

[![Decky Loader](https://img.shields.io/badge/Decky-Plugin-blue.svg)](https://github.com/SteamDeckHomebrew/decky-loader)
[![License](https://img.shields.io/badge/License-BSD_3--Clause-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-SteamOS%20%7C%20Linux%20%7C%20Bazzite-orange.svg)](https://github.com/SteamDeckHomebrew)
[![Author](https://img.shields.io/badge/Author-ElYarim-yellow.svg)](https://github.com/ElYarim)

**Deckamine** brings Apple-style **Vehicle Motion Cues** to handheld gaming devices running SteamOS / Linux (such as the ASUS ROG Ally, ROG Ally X, and Steam Deck).

By displaying subtle, animated inertia dots along the screen edges that respond in real time to real-world vehicle accelerations and centrifugal turns, Deckamine resolves the sensory conflict between your inner ear (vestibular system) and eyes, significantly reducing or preventing motion sickness (kinetosis) when gaming in moving cars, trains, buses, or airplanes.

---

## ✨ Features

- **In-Game Overlay Persistence:** Leverages GameScope's composition state pipeline to remain pinned and visible while playing any game, without disappearing when closing the Decky menu.
- **Hardware IMU Integration:** Reads directly from the onboard Linux Industrial I/O (`/sys/bus/iio/devices/`) sensors (such as Bosch BMI323) with a continuous exponential moving average (EMA) filter.
- **Spring-Damper Physics Engine:** Simulates realistic physical inertia at native display refresh rates (60 Hz / 120 Hz) using `requestAnimationFrame`.
- **Zero Impact on Gaming Performance:**
  - Direct imperative DOM transforms.
  - Zero React re-renders during gameplay.
  - No canvas blur memory leaks.
- **Bicolor Dot Design:** Contrasted dots (bright core with dark shadow) ensure clear visibility across dark or bright game backgrounds.
- **Full Customization:**
  - Sensitivity slider (1.0x to 10.0x).
  - Deadzone threshold to filter micro-vibrations.
  - Dot size (8px to 22px) and opacity (30% to 100%).
  - Color presets (White, Cyan, Amber, Mint, Hot Pink).
  - Axis inversion (Invert X / Invert Y).
  - One-tap neutral calibration button.
  - Live real-time G-force telemetry monitor.

---

## 🔒 Security & Privacy

Deckamine was designed adhering to the highest security standards:
- **100% Offline:** No network requests, zero telemetry, no external connections.
- **No Input Interception:** Uses `pointer-events: none` on the overlay, guaranteeing all touches, gamepad inputs, and clicks pass directly to the game.
- **Read-Only Hardware Access:** Only reads accelerometer raw files from `/sys/bus/iio/devices/`. No root commands or privileged execution.
- **Safe Codebase:** No `eval()`, no `subprocess`, no dynamic shell execution.

---

## 📦 Installation

### From the Decky Loader Store (Recommended)
1. Open the Decky Loader menu in Game Mode.
2. Go to the **Plugin Store** (shopping bag icon).
3. Search for **Deckamine** and click **Install**.

### Manual Installation
1. Download the latest `deckamine.zip` from the [Releases](https://github.com/ElYarim/deckamine/releases) page.
2. Extract the `deckamine` folder into:
   ```bash
   /home/deck/homebrew/plugins/deckamine
   ```
3. Restart Decky Loader:
   ```bash
   sudo systemctl restart plugin_loader
   ```

---

## 🛠️ Building from Source

### Prerequisites
- Node.js (v18+)
- `pnpm` (v9+)

### Build Steps
```bash
# Clone the repository
git clone https://github.com/ElYarim/deckamine.git
cd deckamine

# Install dependencies
pnpm install

# Build frontend bundle
pnpm run build
```
The compiled output will be generated inside the `dist/` directory (`dist/index.js`).

---

## 📄 License

This project is licensed under the [BSD 3-Clause License](LICENSE) by **ElYarim**.
