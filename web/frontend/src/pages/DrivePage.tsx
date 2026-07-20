import { useCallback, useEffect, useRef, useState } from "react";
import {
  cameraPreviewUrl,
  CoverageConfig,
  CoverageStatus,
  DriveConfig,
  DriveStatus,
  fetchCoverageConfig,
  fetchCoverageStatus,
  fetchDriveConfig,
  fetchDriveStatus,
  lidarPreviewUrl,
  sendDriveCommand,
  startCoverage,
  stopCoverage,
  stopDrive,
  updateCoverageConfig,
  updateDriveConfig,
} from "../api";
import DriveJoystick from "../components/DriveJoystick";

const KEEPALIVE_MS = 300;
const PREVIEW_REFRESH_MS = 66; // ~15 fps, passend zu camera.preview_fps
const LIDAR_REFRESH_MS = 500; // ~2 fps, passend zu lidar.preview_fps
const DRIVE_STATUS_POLL_MS = 500; // Encoder-Anzeige aktualisieren

function formatEncoderCm(m: number | null | undefined): string {
  if (m == null) return "–";
  return `${(m * 100).toFixed(1)} cm`;
}

const COVERAGE_STATE_LABELS: Record<CoverageStatus["state"], string> = {
  idle: "Bereit",
  driving: "fährt Bahn",
  turning: "dreht",
  avoiding: "weicht Hindernis aus",
  done: "Bereich abgefahren",
  aborted: "abgebrochen",
};

type Vec = { left: number; right: number };

const FORWARD: Vec = { left: 1, right: 1 };
const BACKWARD: Vec = { left: -1, right: -1 };
const TURN_LEFT: Vec = { left: -1, right: 1 };
const TURN_RIGHT: Vec = { left: 1, right: -1 };

/** Pfeiltasten: links=rückwärts, rechts=vorwärts, hoch=rechts drehen, runter=links drehen */
const ARROW_KEY_MAP: Record<string, Vec> = {
  ArrowLeft: BACKWARD,
  ArrowDown: TURN_LEFT,
  ArrowRight: FORWARD,
  ArrowUp: TURN_RIGHT,
};

function useSmoothPreview(urlFactory: (t: number) => string, refreshMs: number): string {
  const [src, setSrc] = useState(() => urlFactory(Date.now()));

  useEffect(() => {
    const timer = window.setInterval(() => {
      const next = urlFactory(Date.now());
      const img = new Image();
      img.onload = () => setSrc(next);
      img.onerror = () => undefined;
      img.src = next;
    }, refreshMs);
    return () => clearInterval(timer);
  }, [urlFactory, refreshMs]);

  return src;
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(query).matches : false
  );
  useEffect(() => {
    const m = window.matchMedia(query);
    const handler = () => setMatches(m.matches);
    handler();
    m.addEventListener("change", handler);
    return () => m.removeEventListener("change", handler);
  }, [query]);
  return matches;
}

export default function DrivePage() {
  const [config, setConfig] = useState<DriveConfig | null>(null);
  const [status, setStatus] = useState<DriveStatus | null>(null);
  const [speed, setSpeed] = useState(0.6);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [previewAvailable, setPreviewAvailable] = useState(true);
  const previewSrc = useSmoothPreview(cameraPreviewUrl, PREVIEW_REFRESH_MS);
  const [lidarAvailable, setLidarAvailable] = useState(true);
  const lidarSrc = useSmoothPreview(lidarPreviewUrl, LIDAR_REFRESH_MS);

  const [coverage, setCoverage] = useState<CoverageStatus | null>(null);
  const [coverageConfig, setCoverageConfig] = useState<CoverageConfig | null>(null);
  const [areaLength, setAreaLength] = useState(1.0);
  const [areaWidth, setAreaWidth] = useState(1.0);

  const isTouch = useMediaQuery("(pointer: coarse)");
  const isPortrait = useMediaQuery("(orientation: portrait)");

  const keepalive = useRef<number | null>(null);
  const current = useRef<Vec>({ left: 0, right: 0 });

  useEffect(() => {
    fetchDriveConfig().then(setConfig).catch(() => undefined);
    fetchDriveStatus().then(setStatus).catch(() => undefined);
    fetchCoverageConfig().then(setCoverageConfig).catch(() => undefined);
    fetchCoverageStatus().then(setCoverage).catch(() => undefined);
    const drivePoll = setInterval(
      () => fetchDriveStatus().then(setStatus).catch(() => undefined),
      DRIVE_STATUS_POLL_MS
    );
    const coveragePoll = setInterval(
      () => fetchCoverageStatus().then(setCoverage).catch(() => undefined),
      1000
    );
    return () => {
      clearInterval(drivePoll);
      clearInterval(coveragePoll);
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

  const startKeepalive = useCallback(() => {
    const fire = () =>
      sendDriveCommand(current.current.left, current.current.right)
        .then(setStatus)
        .catch((e) => setError(e.message));
    fire();
    clearKeepalive();
    keepalive.current = window.setInterval(fire, KEEPALIVE_MS);
  }, [clearKeepalive]);

  const press = useCallback(
    (vec: Vec) => {
      setError(null);
      current.current = vec;
      startKeepalive();
    },
    [startKeepalive]
  );

  // Joystick: continuous updates while held (direction + magnitude = speed)
  const joyStart = useCallback(() => {
    setError(null);
    current.current = { left: 0, right: 0 };
    startKeepalive();
  }, [startKeepalive]);

  const joyChange = useCallback((left: number, right: number) => {
    current.current = { left, right };
  }, []);

  useEffect(() => () => clearKeepalive(), [clearKeepalive]);

  useEffect(() => {
    const keyMap: Record<string, Vec> = {
      ...ARROW_KEY_MAP,
      w: FORWARD,
      s: BACKWARD,
      a: TURN_LEFT,
      d: TURN_RIGHT,
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

  const coverageActive =
    coverage?.state === "driving" ||
    coverage?.state === "turning" ||
    coverage?.state === "avoiding";

  async function handleStartCoverage() {
    setError(null);
    try {
      setCoverage(await startCoverage(areaLength, areaWidth));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    }
  }

  async function handleStopCoverage() {
    setError(null);
    try {
      setCoverage(await stopCoverage());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    }
  }

  async function saveCoverageConfig() {
    if (!coverageConfig) return;
    setError(null);
    try {
      const saved = await updateCoverageConfig(coverageConfig);
      setCoverageConfig(saved);
      setMessage("Fahrparameter gespeichert");
      setTimeout(() => setMessage(null), 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    }
  }

  const numberField = (
    label: string,
    key: keyof CoverageConfig,
    step: number,
    hint?: string
  ) =>
    coverageConfig && (
      <label>
        {label}
        {hint && <span className="muted">{hint}</span>}
        <input
          type="number"
          step={step}
          min={0}
          value={coverageConfig[key] as number}
          onChange={(e) =>
            setCoverageConfig({ ...coverageConfig, [key]: Number(e.target.value) })
          }
        />
      </label>
    );

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
        {status?.encoder_enabled && (
          <>
            <span className={`badge ${(status.encoder_left_counts ?? 0) !== 0 ? "ok" : "warn"}`}>
              Enc. links: {formatEncoderCm(status.encoder_left_m)}
              {status.encoder_left_counts != null && ` (${status.encoder_left_counts} Imp.)`}
            </span>
            <span className={`badge ${(status.encoder_right_counts ?? 0) !== 0 ? "ok" : "warn"}`}>
              Enc. rechts: {formatEncoderCm(status.encoder_right_m)}
              {status.encoder_right_counts != null && ` (${status.encoder_right_counts} Imp.)`}
            </span>
          </>
        )}
      </div>

      <div className="drive-encoder-row">
        <h2 className="drive-encoder-title">Rad-Encoder (Strecke seit Core-Start)</h2>
        {status?.encoder_enabled ? (
          <>
            <div className="drive-encoder-values">
              <span className={`badge ${(status.encoder_left_counts ?? 0) !== 0 ? "ok" : "warn"}`}>
                Kette links: {formatEncoderCm(status.encoder_left_m)}
                {status.encoder_left_counts != null && (
                  <span className="encoder-count"> · {status.encoder_left_counts} Impulse</span>
                )}
              </span>
              <span className={`badge ${(status.encoder_right_counts ?? 0) !== 0 ? "ok" : "warn"}`}>
                Kette rechts: {formatEncoderCm(status.encoder_right_m)}
                {status.encoder_right_counts != null && (
                  <span className="encoder-count"> · {status.encoder_right_counts} Impulse</span>
                )}
              </span>
              <span className="badge">
                Mittel:{" "}
                {status.encoder_left_m != null && status.encoder_right_m != null
                  ? formatEncoderCm((status.encoder_left_m + status.encoder_right_m) / 2)
                  : "–"}
              </span>
            </div>
            {(status.encoder_left_counts === 0 || status.encoder_right_counts === 0) && (
              <p className="warn drive-encoder-hint">
                Ein Encoder zählt 0 Impulse — Kabel prüfen (links GPIO 21/24, rechts GPIO 14/15).
                Rad von Hand drehen und Impulse beobachten. A/B vertauscht? In{" "}
                <code>config/local.yaml</code> unter <code>encoder.left</code> tauschen.
              </p>
            )}
          </>
        ) : (
          <p className="muted drive-encoder-off">
            Encoder nicht aktiv — in <code>config/local.yaml</code> unter{" "}
            <code>encoder.enabled: true</code> setzen und{" "}
            <code>pulses_per_rev</code> + <code>wheel_diameter_mm</code> kalibrieren.
            Danach <code>sudo systemctl restart maehbot-core maehbot-web</code>.
          </p>
        )}
      </div>

      <div className={`drive-layout ${isTouch ? "touch" : ""}`}>
        {isTouch ? (
          <div className="drive-controls joystick-controls">
            <DriveJoystick
              onStart={joyStart}
              onChange={joyChange}
              onEnd={release}
              disabled={config ? !config.enabled : false}
            />
            <p className="muted joystick-hint">
              Finger ziehen: Richtung bestimmt die Fahrtrichtung, der Abstand zur Mitte das Tempo.
              Loslassen stoppt.
            </p>
            {isPortrait && (
              <p className="warn">Für die Steuerung bitte das Gerät ins Querformat drehen.</p>
            )}
          </div>
        ) : (
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
              {padBtn("▲", TURN_RIGHT)}
              <div />
              {padBtn("◀", BACKWARD)}
              <button type="button" className="drive-btn stop" onClick={release}>
                ■
              </button>
              {padBtn("▶", FORWARD)}
              <div />
              {padBtn("▼", TURN_LEFT)}
              <div />
            </div>
          </div>
        )}

        <div className="drive-preview camera-panel">
          <h2>Kamerabild</h2>
          <img
            src={previewSrc}
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

        <div className="drive-preview lidar-panel">
          <h2>LiDAR</h2>
          <img
            src={lidarSrc}
            alt="LiDAR-Rundumsicht"
            className="lidar-preview"
            style={{ display: lidarAvailable ? "block" : "none" }}
            onError={() => setLidarAvailable(false)}
            onLoad={() => setLidarAvailable(true)}
          />
          {!lidarAvailable && (
            <div className="drive-preview-placeholder">
              <p className="muted">LiDAR-Bild nicht verfügbar.</p>
            </div>
          )}
        </div>
      </div>

      <div className="coverage-panel">
        <h2>Bereich abfahren</h2>
        <p className="muted">
          Der Roboter fährt ab seiner aktuellen Position eine Rechteck-Spirale nach außen, bis
          der angegebene Bereich abgedeckt ist. Der LiDAR überwacht dabei Hindernisse.
        </p>
        <div className="coverage-controls">
          <label>
            Länge (m)
            <input
              type="number"
              step={0.1}
              min={0.1}
              value={areaLength}
              disabled={coverageActive}
              onChange={(e) => setAreaLength(Number(e.target.value))}
            />
          </label>
          <label>
            Breite (m)
            <input
              type="number"
              step={0.1}
              min={0.1}
              value={areaWidth}
              disabled={coverageActive}
              onChange={(e) => setAreaWidth(Number(e.target.value))}
            />
          </label>
          {!coverageActive ? (
            <button type="button" onClick={handleStartCoverage}>
              Bereich abfahren
            </button>
          ) : (
            <button type="button" className="danger-btn" onClick={handleStopCoverage}>
              Fahrt stoppen
            </button>
          )}
        </div>
        {coverage && (
          <div className="drive-status-row">
            <span className={`badge ${coverageActive ? "ok" : coverage.state === "aborted" ? "error" : ""}`}>
              {COVERAGE_STATE_LABELS[coverage.state]}
            </span>
            {coverage.leg_count > 0 && (
              <span className="badge">
                Bahn {Math.min(coverage.leg_index + 1, coverage.leg_count)} / {coverage.leg_count}
              </span>
            )}
            {coverage.leg_count > 0 && (
              <span className="badge">Fortschritt: {coverage.progress_percent.toFixed(0)} %</span>
            )}
            <span className={`badge ${coverage.lidar_connected ? "ok" : "warn"}`}>
              {coverage.lidar_connected ? "LiDAR verbunden" : "LiDAR nicht verbunden"}
            </span>
          </div>
        )}
        {coverage?.error && <p className="error">{coverage.error}</p>}
      </div>

      {coverageConfig && (
        <div className="coverage-panel">
          <h2>Parameter Spiralfahrt</h2>
          <p className="muted">
            Ohne Drehgeber wird zeitbasiert gefahren: „Tempo (m/s)“ und „Drehrate (°/s)“ sind
            Kalibrierwerte — auf dem Rasen messen (z. B. 2 m fahren und Zeit stoppen) und hier
            eintragen.
          </p>
          <div className="coverage-grid">
            {numberField("Kettentempo geradeaus (0–1)", "drive_speed", 0.05)}
            {numberField("Kettentempo drehen (0–1)", "turn_speed", 0.05)}
            {numberField("Tempo (m/s) — Kalibrierwert", "speed_m_s", 0.01)}
            {numberField("Drehrate (°/s) — Kalibrierwert", "pivot_deg_s", 1)}
            {numberField("Erstes Segment (m)", "first_leg_m", 0.05)}
            {numberField("Zweites Segment (m)", "second_leg_m", 0.05)}
            {numberField("Bahnabstand (m)", "track_spacing_m", 0.05)}
            <label>
              Drehrichtung
              <select
                value={coverageConfig.turn_direction}
                onChange={(e) =>
                  setCoverageConfig({
                    ...coverageConfig,
                    turn_direction: e.target.value as "left" | "right",
                  })
                }
              >
                <option value="left">links</option>
                <option value="right">rechts</option>
              </select>
            </label>
            {numberField("Hindernis-Stoppdistanz (m)", "obstacle_stop_m", 0.05)}
            {numberField("Hindernis-Sektor (°)", "obstacle_sector_deg", 5)}
            {numberField("Wartezeit vor Ausweichen (s)", "obstacle_wait_s", 0.5)}
            {numberField("Ausweichstrecke (m)", "detour_m", 0.05)}
            {numberField("Max. Ausweichversuche", "max_avoid_attempts", 1)}
          </div>
          <button type="button" onClick={saveCoverageConfig}>
            Fahrparameter speichern
          </button>
        </div>
      )}

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
