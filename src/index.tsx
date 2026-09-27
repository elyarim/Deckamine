import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  SliderField,
  DropdownItem,
  staticClasses,
} from "@decky/ui";
import {
  addEventListener,
  removeEventListener,
  callable,
  definePlugin,
  routerHook,
  toaster,
} from "@decky/api";
import React, { useState, useEffect, useRef } from "react";
import { FaCar } from "react-icons/fa";

const COMPOSITION_TAG = "deckamine_motion_cues";

function getCompositionStore(element: HTMLElement | null): any {
  if (!element) return null;
  const target = element.parentElement || element;
  const fiberKey = Object.keys(target).find((k) => k.startsWith("__reactFiber"));
  if (!fiberKey) return null;
  let fiber = (target as any)[fiberKey];
  let depth = 0;
  while (fiber && depth < 250) {
    depth++;
    if (fiber.memoizedProps?.value?.CompositionStateStore) {
      return fiber.memoizedProps.value.CompositionStateStore;
    }
    fiber = fiber.return;
  }
  return null;
}

const rpcCalibrate = callable<[], boolean>("calibrate");
type DeckamineSettings = {
  enabled: boolean;
  sensitivity: number;
  deadzone: number;
  invert_x: boolean;
  invert_y: boolean;
  dot_size: number;
  dot_color: string;
  dot_opacity: number;
};
type SensorStatus = { status: string; message: string | null; sensor: string | null };
type MotionEvent = { x: number; y: number; active: boolean };

const rpcGetSettings = callable<[], Partial<DeckamineSettings>>("get_settings");
const rpcSetSettings = callable<[settings: Partial<DeckamineSettings>], boolean>("set_settings");
const rpcGetSensorStatus = callable<[], SensorStatus>("get_sensor_status");

type Listener = () => void;
class DeckamineStore {
  private listeners = new Set<Listener>();
  enabled = false;
  sensitivity = 5;
  deadzone = 200;
  invert_x = false;
  invert_y = false;
  dot_size = 14;
  dot_color = "#ffffff";
  dot_opacity = 0.95;
  target_x = 0;
  target_y = 0;

  subscribe(l: Listener) { this.listeners.add(l); return () => { this.listeners.delete(l); }; }
  notify() { this.listeners.forEach((l) => l()); }
  setSettings(patch: Partial<DeckamineSettings>) { Object.assign(this, patch); this.notify(); }
  setMotionDirect(x: number, y: number) { this.target_x = x; this.target_y = y; }
}
const store = new DeckamineStore();

const DOT_DEFS: [number, number, boolean][] = [
  [0.04, 0.18, false], [0.04, 0.38, true],  [0.04, 0.62, false], [0.04, 0.82, true],
  [0.96, 0.18, true],  [0.96, 0.38, false], [0.96, 0.62, true],  [0.96, 0.82, false],
  [0.22, 0.04, false], [0.40, 0.04, true],  [0.60, 0.04, false], [0.78, 0.04, true],
  [0.22, 0.96, true],  [0.40, 0.96, false], [0.60, 0.96, true],  [0.78, 0.96, false],
];
const DOT_SCALE = [1.0, 0.72, 1.0, 0.72, 0.72, 1.0, 0.72, 1.0, 1.0, 0.72, 1.0, 0.72, 0.72, 1.0, 0.72, 1.0];

class DotOverlay {
  private wrapper: HTMLDivElement;
  private dots: HTMLDivElement[] = [];
  private springs: [number, number, number, number][] = DOT_DEFS.map(() => [0, 0, 0, 0]);
  private raf = 0;
  private alive = false;
  private readonly K = 180;
  private readonly D = 18;

  constructor(container: HTMLElement) {
    this.wrapper = document.createElement("div");
    Object.assign(this.wrapper.style, {
      position: "fixed",
      inset: "0",
      width: "100vw",
      height: "100vh",
      pointerEvents: "none",
      zIndex: "2147483647",
      background: "transparent",
      backgroundColor: "transparent",
      overflow: "hidden",
      display: "none",
    });
    container.appendChild(this.wrapper);

    for (let i = 0; i < DOT_DEFS.length; i++) {
      const [fx, fy, isDark] = DOT_DEFS[i];
      const d = document.createElement("div");
      const sz = store.dot_size * DOT_SCALE[i];
      Object.assign(d.style, {
        position: "absolute",
        width: sz + "px",
        height: sz + "px",
        borderRadius: "50%",
        pointerEvents: "none",
        willChange: "transform",
        transform: "translate3d(0,0,0)",
        left: (fx * 100) + "vw",
        top:  (fy * 100) + "vh",
        marginLeft: (-sz / 2) + "px",
        marginTop:  (-sz / 2) + "px",
        ...(isDark
          ? { background: "rgba(10,10,14,0.90)", boxShadow: "0 0 0 1.1px rgba(255,255,255,0.28)" }
          : { background: "radial-gradient(circle at 35% 35%, #fff 0%, #e6e6e6 60%, #b4b4b4 100%)", boxShadow: "0 1px 4px rgba(0,0,0,0.4)" }
        ),
        opacity: String(store.dot_opacity),
      });
      this.wrapper.appendChild(d);
      this.dots.push(d);
    }
  }

  private syncStyle() {
    for (let i = 0; i < this.dots.length; i++) {
      const [,, isDark] = DOT_DEFS[i];
      const sz = store.dot_size * DOT_SCALE[i];
      const d = this.dots[i];
      d.style.width      = sz + "px";
      d.style.height     = sz + "px";
      d.style.marginLeft = (-sz / 2) + "px";
      d.style.marginTop  = (-sz / 2) + "px";
      d.style.opacity    = String(store.dot_opacity);
      if (isDark) {
        d.style.background = "rgba(10,10,14,0.90)";
        d.style.boxShadow  = "0 0 0 1.1px rgba(255,255,255,0.28)";
      } else {
        const c = store.dot_color;
        d.style.background = `radial-gradient(circle at 35% 35%, ${c} 0%, ${c}cc 60%, ${c}88 100%)`;
        d.style.boxShadow  = "0 1px 4px rgba(0,0,0,0.4)";
      }
    }
  }

  private unsub: (() => void) | null = null;

  start() {
    if (this.alive) return;
    this.alive = true;
    this.wrapper.style.display = "block";
    this.syncStyle();
    if (!this.unsub) this.unsub = store.subscribe(() => this.syncStyle());
    let last = performance.now();
    const loop = (now: number) => {
      if (!this.alive) return;
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      const tx = store.target_x;
      const ty = store.target_y;
      for (let i = 0; i < this.springs.length; i++) {
        const s = this.springs[i];
        s[2] += (-this.K * (s[0] - tx) - this.D * s[2]) * dt;
        s[3] += (-this.K * (s[1] - ty) - this.D * s[3]) * dt;
        s[0] += s[2] * dt;
        s[1] += s[3] * dt;
        this.dots[i].style.transform = "translate3d(" + s[0].toFixed(1) + "px," + s[1].toFixed(1) + "px,0)";
      }
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop() {
    this.alive = false;
    cancelAnimationFrame(this.raf);
    this.springs.forEach((spring, index) => {
      spring.fill(0);
      this.dots[index].style.transform = "translate3d(0,0,0)";
    });
    this.wrapper.style.display = "none";
  }

  destroy() {
    this.stop();
    if (this.unsub) { this.unsub(); this.unsub = null; }
    this.wrapper.remove();
  }
}

const GlobalMotionOverlay: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const overlayRef   = useRef<DotOverlay | null>(null);
  const [enabled, setEnabled] = useState(store.enabled);

  useEffect(() => {
    return store.subscribe(() => {
      setEnabled(store.enabled);
      if (store.enabled) overlayRef.current?.start();
      else               overlayRef.current?.stop();
    });
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;
    const ov = new DotOverlay(containerRef.current);
    overlayRef.current = ov;
    if (store.enabled) ov.start();
    return () => ov.destroy();
  }, []);

  useEffect(() => {
    let compStore: any = null;
    let requested = false;
    const sync = () => {
      if (!compStore) compStore = getCompositionStore(containerRef.current);
      if (!compStore?.AddMinimumCompositionStateRequest) return;
      if (store.enabled && !requested) {
        try { compStore.AddMinimumCompositionStateRequest(1, COMPOSITION_TAG); requested = true; } catch (_) {}
      } else if (!store.enabled && requested) {
        try { compStore.RemoveMinimumCompositionStateRequest(1, COMPOSITION_TAG); requested = false; } catch (_) {}
      }
    };
    sync();
    const iv = setInterval(sync, 1500);
    return () => {
      clearInterval(iv);
      if (compStore && requested) try { compStore.RemoveMinimumCompositionStateRequest(1, COMPOSITION_TAG); } catch (_) {}
    };
  }, [enabled]);

  return (
    <div
      ref={containerRef}
      id="deckamine-global-overlay"
      style={{
        position: "fixed",
        inset: 0,
        width: "100vw",
        height: "100vh",
        pointerEvents: "none",
        zIndex: 2147483647,
        overflow: "hidden",
        background: "transparent",
        backgroundColor: "transparent",
      }}
    />
  );
};

const COLOR_PRESETS = [
  { label: "Bicolor (Recomendado)", value: "#ffffff" },
  { label: "Blanco Neon",          value: "#e0e0e0" },
  { label: "Cian",                 value: "#00e5ff" },
  { label: "Ambar",                value: "#ffb300" },
  { label: "Verde",                value: "#00e676" },
];
const SENSOR_STATUS_LABELS: Record<string, string> = {
  starting: "Esperando lecturas",
  ready: "Disponible",
  unavailable: "No detectado",
  error: "Error de lectura",
};

function Content() {
  const [, setTick] = useState(0);
  const [calibrating, setCalibrating] = useState(false);
  const [liveX, setLiveX] = useState(0);
  const [liveY, setLiveY] = useState(0);
  const [sensorStatus, setSensorStatus] = useState<SensorStatus>({
    status: "starting",
    message: null,
    sensor: null,
  });

  useEffect(() => { return store.subscribe(() => setTick((t) => t + 1)); }, []);

  useEffect(() => {
    const iv = setInterval(() => {
      setLiveX(parseFloat(store.target_x.toFixed(1)));
      setLiveY(parseFloat(store.target_y.toFixed(1)));
    }, 200);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    let receivedEvent = false;
    const listener = addEventListener<[data: SensorStatus]>("deckamine_sensor_status", (status) => {
      receivedEvent = true;
      setSensorStatus(status);
    });
    rpcGetSensorStatus()
      .then((status) => {
        if (!receivedEvent) setSensorStatus(status);
      })
      .catch((error) => {
        toaster.toast({ title: "Deckamine", body: `No se pudo consultar el sensor: ${String(error)}` });
      });
    return () => removeEventListener("deckamine_sensor_status", listener);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const s = await rpcGetSettings();
        if (s) store.setSettings(s);
      } catch (error) {
        toaster.toast({ title: "Deckamine", body: `No se pudieron cargar los ajustes: ${String(error)}` });
      }
    })();
  }, []);

  const save = async (patch: Partial<DeckamineSettings>) => {
    try {
      await rpcSetSettings(patch);
      store.setSettings(patch);
    } catch (error) {
      toaster.toast({ title: "Deckamine", body: `No se pudieron guardar los ajustes: ${String(error)}` });
    }
  };

  useEffect(() => {
    const calibrationListener = addEventListener<[data: { status: string; message?: string }]>(
      "deckamine_calibrated",
      (data) => {
        setCalibrating(false);
        if (data?.status === "ok") {
          toaster.toast({ title: "Deckamine", body: "Calibración completada." });
        } else {
          toaster.toast({
            title: "Deckamine",
            body: `Falló la calibración: ${data?.message || "error de lectura del sensor"}`,
          });
        }
      }
    );
    return () => removeEventListener("deckamine_calibrated", calibrationListener);
  }, []);

  const handleCalibrate = async () => {
    setCalibrating(true);
    toaster.toast({ title: "Deckamine", body: "Mantén la consola en tu postura natural..." });
    try {
      const started = await rpcCalibrate();
      if (!started) throw new Error("el sensor no aceptó la calibración");
    } catch (error) {
      setCalibrating(false);
      toaster.toast({ title: "Deckamine", body: `No se pudo iniciar la calibración: ${String(error)}` });
    }
  };

  const handleTest = () => {
    store.setMotionDirect(38, 0);
    setTimeout(() => store.setMotionDirect(-38, 0), 350);
    setTimeout(() => store.setMotionDirect(0, 0),   700);
  };

  return (
    <div>
      <PanelSection title="Estado">
        <PanelSectionRow>
          <div style={{ fontSize: "11px", opacity: 0.75, padding: "2px 0" }}>
            Sensor: <strong>{sensorStatus.sensor || SENSOR_STATUS_LABELS[sensorStatus.status] || sensorStatus.status}</strong>
            {sensorStatus.sensor ? ` (${SENSOR_STATUS_LABELS[sensorStatus.status] || sensorStatus.status})` : ""}
            {sensorStatus.message ? ` — ${sensorStatus.message}` : ""}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", opacity: 0.75, padding: "2px 0" }}>
            <span>X: <strong>{liveX.toFixed(1)}</strong></span>
            <span>Y: <strong>{liveY.toFixed(1)}</strong></span>
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Activar Motion Cues" description="Puntos en bordes para evitar mareos." checked={store.enabled} onChange={(v) => save({ enabled: v })} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleCalibrate} disabled={calibrating}>
            {calibrating ? "Calibrando..." : "Calibrar Posicion"}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleTest}>Probar Movimiento</ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Dinamica">
        <PanelSectionRow>
          <SliderField label="Sensibilidad" value={store.sensitivity} min={1} max={10} step={1} showValue onChange={(v) => save({ sensitivity: v })} />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField label="Deadzone" value={store.deadzone} min={50} max={600} step={25} showValue onChange={(v) => save({ deadzone: v })} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Invertir X" checked={store.invert_x} onChange={(v) => save({ invert_x: v })} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Invertir Y" checked={store.invert_y} onChange={(v) => save({ invert_y: v })} />
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Visual">
        <PanelSectionRow>
          <SliderField label="Tamano" value={store.dot_size} min={8} max={22} step={1} showValue onChange={(v) => save({ dot_size: v })} />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField label="Opacidad" value={Math.round(store.dot_opacity * 100)} min={30} max={100} step={5} showValue onChange={(v) => save({ dot_opacity: v / 100 })} />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem label="Color" rgOptions={COLOR_PRESETS.map((p) => ({ label: p.label, data: p.value }))} selectedOption={store.dot_color} onChange={(o) => save({ dot_color: o.data })} />
        </PanelSectionRow>
      </PanelSection>

    </div>
  );
}

export default definePlugin(() => {
  routerHook.addGlobalComponent("DeckamineMotionOverlay", GlobalMotionOverlay);
  const motionListener = addEventListener<[data: MotionEvent]>("deckamine_motion", (data) => {
    if (data?.active && Number.isFinite(data.x) && Number.isFinite(data.y)) {
      store.setMotionDirect(data.x, data.y);
    } else {
      store.setMotionDirect(0, 0);
    }
  });
  return {
    name: "Deckamine",
    titleView: <div className={staticClasses.Title}>Deckamine</div>,
    content: <Content />,
    icon: <FaCar />,
    alwaysRender: true,
    onDismount() {
      removeEventListener("deckamine_motion", motionListener);
      routerHook.removeGlobalComponent("DeckamineMotionOverlay");
    },
  };
});