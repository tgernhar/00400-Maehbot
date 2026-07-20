import { useEffect, useState } from "react";
import {
  fetchServoConfig,
  fetchServoStatus,
  ServoConfig,
  ServoName,
  ServoStatus,
  ServoStep,
  startServoHome,
  startServoStep,
  startServoTest,
  visionCameraPreviewUrl,
} from "../api";

const PREVIEW_REFRESH_MS = 200;

const SERVO_OPTIONS: { key: ServoName; label: string }[] = [
  { key: "position", label: "Servo 1 – Positionierung" },
  { key: "tension", label: "Servo 2 – Spannservo" },
  { key: "trigger", label: "Servo 3 – Betätigung" },
];

const STATE_LABELS: Record<string, string> = {
  idle: "Bereit",
  homing: "Grundstellung wird angefahren…",
  testing: "Testlauf läuft…",
  sweeping: "Einzeltest läuft…",
};

const CORE_STALE_SECONDS = 5;

function coreReachable(status: ServoStatus | null): boolean {
  if (!status?.updated_at) return false;
  return Date.now() / 1000 - status.updated_at < CORE_STALE_SECONDS;
}

function stepsFromConfig(cfg: ServoConfig): ServoStep[] {
  const seq = cfg.test_sequence;
  if (!Array.isArray(seq) || seq.length === 0) {
    throw new Error(
      "Servo-Konfiguration unvollständig (test_sequence fehlt). Bitte Frontend-Build deployen."
    );
  }
  return seq.map((s) => ({
    servo: s.servo,
    angle: s.angle,
    hold_until_step: s.hold_until_step ?? null,
  }));
}

export default function SprayPage() {
  const [config, setConfig] = useState<ServoConfig | null>(null);
  const [steps, setSteps] = useState<ServoStep[] | null>(null);
  const [status, setStatus] = useState<ServoStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [previewTick, setPreviewTick] = useState(0);
  const [previewError, setPreviewError] = useState(false);
  const busy = status != null && status.state !== "idle";
  const coreOnline = coreReachable(status);

  useEffect(() => {
    fetchServoConfig()
      .then((cfg) => {
        setConfig(cfg);
        setSteps(stepsFromConfig(cfg));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Fehler"));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = () => {
      fetchServoStatus()
        .then((s) => {
          if (!cancelled) setStatus(s);
        })
        .catch(() => undefined);
    };
    poll();
    const t = setInterval(poll, 1000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    const t = setInterval(() => setPreviewTick(Date.now()), PREVIEW_REFRESH_MS);
    return () => clearInterval(t);
  }, []);

  function updateStep(index: number, patch: Partial<ServoStep>) {
    if (!steps) return;
    setSteps(steps.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  }

  function updateStepHold(index: number, raw: string) {
    if (!steps) return;
    if (raw.trim() === "") {
      setError(null);
      updateStep(index, { hold_until_step: null });
      return;
    }
    const value = Number(raw);
    const minStep = index + 1;
    if (!Number.isFinite(value) || value < minStep || value > steps.length) {
      setError(
        `Halten-bis-Schritt in Schritt ${minStep}: Wert zwischen ${minStep} und ${steps.length}`
      );
      return;
    }
    setError(null);
    updateStep(index, { hold_until_step: value });
  }

  function addStep() {
    if (!steps) return;
    setSteps([...steps, { servo: "position", angle: 0, hold_until_step: null }]);
  }

  function removeStep(index: number) {
    if (!steps || steps.length <= 1) return;
    setSteps(steps.filter((_, i) => i !== index));
  }

  async function onTestStep(index: number) {
    if (!steps) return;
    setError(null);
    setMessage(null);
    try {
      setStatus(await startServoStep(steps[index], index + 1));
      setMessage(`Schritt ${index + 1} gestartet`);
      setTimeout(() => setMessage(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  }

  async function onTest() {
    if (!steps) return;
    setError(null);
    setMessage(null);
    try {
      setStatus(await startServoTest(steps));
      setMessage("Testlauf gestartet");
      setTimeout(() => setMessage(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  }

  async function onHome() {
    setError(null);
    setMessage(null);
    try {
      setStatus(await startServoHome());
      setMessage("Grundstellung wird angefahren");
      setTimeout(() => setMessage(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  }

  if (!config || !steps) {
    return (
      <div>
        <h1>Sprühen</h1>
        {error ? <p className="error">{error}</p> : <p>Laden…</p>}
      </div>
    );
  }

  return (
    <div>
      <h1>Sprühen</h1>
      <p className="muted">
        Testablauf: Jeder Schritt fährt einen Servo auf den Verfahrwert. Optional kann
        pro Schritt ein Halte-Schritt gesetzt werden — dann bleibt der Servo bis zu
        diesem Schritt aktiv angesteuert. Leer = nach dem Schritt abschalten.
      </p>
      {status && (
        <p className={busy ? "warn" : "ok"}>
          Status: {STATE_LABELS[status.state] ?? status.state}
        </p>
      )}
      {status && !coreOnline && (
        <p className="error">
          Core-Prozess nicht erreichbar — bitte in einer zweiten SSH-Sitzung starten:{" "}
          <code>python -m core.main</code>
        </p>
      )}
      {status?.error && <p className="error">{status.error}</p>}
      {message && <p className="ok">{message}</p>}
      {error && <p className="error">{error}</p>}

      <section className="live-panel spray-camera-panel">
        <h2>Kamerabild</h2>
        <p className="muted">
          Livebild vom Core — zur Kontrolle der Düsenausrichtung während der Servo-Tests.
        </p>
        <div className="live-viewport">
          <img
            src={visionCameraPreviewUrl(previewTick)}
            alt="Kameravorschau"
            className="camera-preview"
            style={{ opacity: previewError ? 0.35 : 1 }}
            onLoad={() => setPreviewError(false)}
            onError={() => setPreviewError(true)}
          />
          {!previewError && <div className="crosshair-overlay" aria-hidden="true" />}
          {previewError && (
            <p className="muted live-placeholder spray-preview-hint">
              Kameravorschau nicht verfügbar — Core läuft? Endpoint{" "}
              <code>/api/camera/preview/vision</code>
            </p>
          )}
        </div>
      </section>

      <div className="servo-sequence-wrap">
        <table className="servo-sequence-table">
          <thead>
            <tr>
              <th>Schritt</th>
              <th>Servo</th>
              <th>Verfahrwert (°)</th>
              <th>Halten bis Schritt</th>
              <th>Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((step, index) => {
              const limit = config.limits[step.servo];
              const current = status?.angles?.[step.servo];
              const stepNo = index + 1;
              return (
                <tr key={index}>
                  <td>{stepNo}</td>
                  <td>
                    <select
                      value={step.servo}
                      disabled={busy}
                      onChange={(e) =>
                        updateStep(index, { servo: e.target.value as ServoName })
                      }
                    >
                      {SERVO_OPTIONS.map(({ key, label }) => (
                        <option key={key} value={key}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="number"
                      min={limit.min_angle}
                      max={limit.max_angle}
                      step={1}
                      value={step.angle}
                      disabled={busy}
                      onChange={(e) =>
                        updateStep(index, { angle: Number(e.target.value) })
                      }
                    />
                    <span className="muted servo-step-hint">
                      {limit.min_angle}° … {limit.max_angle}°
                      {current != null && ` — aktuell ${current}°`}
                    </span>
                  </td>
                  <td>
                    <input
                      type="number"
                      min={stepNo}
                      max={steps.length}
                      step={1}
                      value={step.hold_until_step ?? ""}
                      disabled={busy}
                      placeholder="—"
                      onChange={(e) => updateStepHold(index, e.target.value)}
                    />
                    <span className="muted servo-step-hint">
                      min. {stepNo}, max. {steps.length}
                    </span>
                  </td>
                  <td className="servo-step-actions">
                    <button
                      type="button"
                      className="servo-step-test"
                      disabled={busy || !coreOnline}
                      onClick={() => onTestStep(index)}
                    >
                      Testen
                    </button>
                    <button
                      type="button"
                      className="servo-step-remove"
                      disabled={busy || steps.length <= 1}
                      onClick={() => removeStep(index)}
                      title="Schritt entfernen"
                    >
                      −
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <button type="button" className="servo-step-add" disabled={busy} onClick={addStep}>
          Schritt hinzufügen
        </button>
      </div>

      <div className="servo-actions">
        <button onClick={onTest} disabled={busy || !coreOnline}>
          Gesamten Ablauf testen
        </button>
        <button onClick={onHome} disabled={busy || !coreOnline}>
          Grundstellung anfahren
        </button>
      </div>
    </div>
  );
}
