import { useCallback, useEffect, useRef, useState } from "react";
import {
  cameraPreviewUrl,
  DriveConfig,
  DriveStatus,
  fetchDriveConfig,
  fetchDriveStatus,
  sendDriveCommand,
  stopDrive,
  updateDriveConfig,
} from "../api";

const KEEPALIVE_MS = 300;
const PREVIEW_REFRESH_MS = 500;

type Vec = { left: number; right: number };

export default function DrivePage() {
  const [config, setConfig] = useState<DriveConfig | null>(null);
  const [status, setStatus] = useState<DriveStatus | null>(null);
  const [speed, setSpeed] = useState(0.6);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [previewTick, setPreviewTick] = useState(Date.now());
  const [previewAvailable, setPreviewAvailable] = useState(true);

  const keepalive = useRef<number | null>(null);
  const current = useRef<Vec>({ left: 0, right: 0 });

  useEffect(() => {
    fetchDriveConfig().then(setConfig).catch(() => undefined);
    fetchDriveStatus().then(setStatus).catch(() => undefined);
    const t = setInterval(() => fetchDriveStatus().then(setStatus).catch(() => undefined), 1000);
    const p = setInterval(() => setPreviewTick(Date.now()), PREVIEW_REFRESH_MS);
    return () => {
      clearInterval(t);
      clearInterval(p);
    };
  }, []);

  const clearKeepalive = useCallback(() => {
    if (keepalive.current !== null) {
      clearInterval(keepalive.current);
      keepalive.current = null;
    }
  }, []);

  const release = useCallback(() => {
    clearKeepalive();
    current.current = { left: 0, right: 0 };
    stopDrive().then(setStatus).catch((e) => setError(e.message));
  }, [clearKeepalive]);

  const press = useCallback(
    (vec: Vec) => {
      setError(null);
      current.current = vec;
      const fire = () =>
        sendDriveCommand(current.current.left, current.current.right)
          .then(setStatus)
          .catch((e) => setError(e.message));
      fire();
      clearKeepalive();
      keepalive.current = window.setInterval(fire, KEEPALIVE_MS);
    },
    [clearKeepalive]
  );

  useEffect(() => () => clearKeepalive(), [clearKeepalive]);

  useEffect(() => {
    const keyMap: Record<string, Vec> = {
      ArrowUp: { left: 1, right: 1 },
      ArrowDown: { left: -1, right: -1 },
      ArrowLeft: { left: -1, right: 1 },
      ArrowRight: { left: 1, right: -1 },
      w: { left: 1, right: 1 },
      s: { left: -1, right: -1 },
      a: { left: -1, right: 1 },
      d: { left: 1, right: -1 },
    };
    const onDown = (e: KeyboardEvent) => {
      const v = keyMap[e.key];
      if (!v || e.repeat) return;
      e.preventDefault();
      press({ left: v.left * speed, right: v.right * speed });
    };
    const onUp = (e: KeyboardEvent) => {
      if (keyMap[e.key]) release();
    };
    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    return () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
    };
  }, [press, release, speed]);

  const padBtn = (label: string, vec: Vec, cls = "") => (
    <button
      type="button"
      className={`drive-btn ${cls}`}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        press({ left: vec.left * speed, right: vec.right * speed });
      }}
      onPointerUp={release}
      onPointerLeave={(e) => {
        if (e.buttons > 0) release();
      }}
      onContextMenu={(e) => e.preventDefault()}
    >
      {label}
    </button>
  );

  async function saveConfig() {
    if (!config) return;
    setError(null);
    try {
      const saved = await updateDriveConfig(config);
      setConfig(saved);
      setMessage("Einstellungen gespeichert");
      setTimeout(() => setMessage(null), 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    }
  }

  return (
    <div>
      <h1>Fahren</h1>
      <p className="muted">
        Knopf gedrückt halten oder Pfeiltasten/WASD verwenden. Beim Loslassen stoppt das Fahrgestell
        automatisch (Totmann-Watchdog).
      </p>
      {error && <p className="error">{error}</p>}
      {message && <p className="ok">{message}</p>}

      {config && !config.enabled && (
        <p className="warn">Fahren ist deaktiviert – unter „Einstellungen“ aktivieren.</p>
      )}

      <div className="drive-status-row">
        <span className="badge">Kette links: {status ? (status.left * 100).toFixed(0) : "–"} %</span>
        <span className="badge">Kette rechts: {status ? (status.right * 100).toFixed(0) : "–"} %</span>
        <span className={`badge ${status?.moving ? "ok" : ""}`}>
          {status?.moving ? "fährt" : "steht"}
        </span>
        <span className={`badge ${status?.enabled ? "ok" : "error"}`}>
          {status?.enabled ? "aktiviert" : "deaktiviert"}
        </span>
      </div>

      <div className="drive-layout">
        <div className="drive-controls">
          <label className="drive-speed">
            Geschwindigkeit: {(speed * 100).toFixed(0)} %
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
            />
          </label>

          <div className="drive-pad">
            <div />
            {padBtn("▲", { left: 1, right: 1 })}
            <div />
            {padBtn("◀", { left: -1, right: 1 })}
            <button type="button" className="drive-btn stop" onClick={release}>
              ■
            </button>
            {padBtn("▶", { left: 1, right: -1 })}
            <div />
            {padBtn("▼", { left: -1, right: -1 })}
            <div />
          </div>
        </div>

        <div className="drive-preview">
          <h2>Kamerabild</h2>
          <img
            src={cameraPreviewUrl(previewTick)}
            alt="Kameravorschau"
            className="camera-preview"
            style={{ display: previewAvailable ? "block" : "none" }}
            onError={() => setPreviewAvailable(false)}
            onLoad={() => setPreviewAvailable(true)}
          />
          {!previewAvailable && (
            <div className="drive-preview-placeholder">
              <p className="muted">Kameravorschau noch nicht verfügbar.</p>
            </div>
          )}
        </div>
      </div>

      {config && (
        <div className="drive-config">
          <h2>Einstellungen</h2>
          <div className="form-grid">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={config.enabled}
                onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
              />
              Fahren aktiviert
            </label>
            <label>
              Max. Geschwindigkeit (0–1)
              <input
                type="number"
                step="0.05"
                min="0"
                max="1"
                value={config.max_speed}
                onChange={(e) => setConfig({ ...config, max_speed: Number(e.target.value) })}
              />
            </label>
            <label>
              Watchdog-Timeout (ms)
              <input
                type="number"
                step="100"
                min="100"
                value={config.watchdog_timeout_ms}
                onChange={(e) =>
                  setConfig({ ...config, watchdog_timeout_ms: Number(e.target.value) })
                }
              />
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={config.invert_left}
                onChange={(e) => setConfig({ ...config, invert_left: e.target.checked })}
              />
              Kette links umkehren
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={config.invert_right}
                onChange={(e) => setConfig({ ...config, invert_right: e.target.checked })}
              />
              Kette rechts umkehren
            </label>
            <button type="button" onClick={saveConfig}>
              Speichern
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
