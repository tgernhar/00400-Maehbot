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
} from "../api";

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

const EMPTY_HOLDS: Record<ServoName, number | null> = {
  position: null,
  tension: null,
  trigger: null,
};

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
  return seq.map((s) => ({ servo: s.servo, angle: s.angle }));
}

function holdsFromConfig(cfg: ServoConfig): Record<ServoName, number | null> {
  return { ...EMPTY_HOLDS, ...(cfg.hold_until_step ?? {}) };
}

function firstStepForServo(steps: ServoStep[], servo: ServoName): number | null {
  const idx = steps.findIndex((s) => s.servo === servo);
  return idx >= 0 ? idx + 1 : null;
}

export default function SprayPage() {
  const [config, setConfig] = useState<ServoConfig | null>(null);
  const [steps, setSteps] = useState<ServoStep[] | null>(null);
  const [holdUntil, setHoldUntil] = useState<Record<ServoName, number | null> | null>(
    null
  );
  const [status, setStatus] = useState<ServoStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const busy = status != null && status.state !== "idle";
  const coreOnline = coreReachable(status);

  useEffect(() => {
    fetchServoConfig()
      .then((cfg) => {
        setConfig(cfg);
        setSteps(stepsFromConfig(cfg));
        setHoldUntil(holdsFromConfig(cfg));
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

  function updateStep(index: number, patch: Partial<ServoStep>) {
    if (!steps) return;
    setSteps(steps.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  }

  function updateHold(servo: ServoName, raw: string) {
    if (!holdUntil || !steps) return;
    if (raw.trim() === "") {
      setHoldUntil({ ...holdUntil, [servo]: null });
      return;
    }
    const value = Number(raw);
    const minStep = firstStepForServo(steps, servo);
    if (!Number.isFinite(value) || value < 1 || value > steps.length) {
      setError(`Halten-bis-Schritt für ${servo}: Wert zwischen 1 und ${steps.length}`);
      return;
    }
    if (minStep != null && value < minStep) {
      setError(`Halten-bis-Schritt für ${servo}: mindestens ${minStep} (erster Schritt)`);
      return;
    }
    setError(null);
    setHoldUntil({ ...holdUntil, [servo]: value });
  }

  function addStep() {
    if (!steps) return;
    setSteps([...steps, { servo: "position", angle: 0 }]);
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
    if (!steps || !holdUntil) return;
    setError(null);
    setMessage(null);
    try {
      setStatus(await startServoTest(steps, holdUntil));
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

  if (!config || !steps || !holdUntil) {
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
        pro Servo ein Halte-Schritt gesetzt werden — dann bleibt der Servo bis zu
        diesem Schritt aktiv angesteuert. Leer = nach jedem eigenen Schritt abschalten.
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

      <div className="servo-hold-wrap">
        <h2>Halten bis Schritt (optional)</h2>
        <table className="servo-hold-table">
          <thead>
            <tr>
              <th>Servo</th>
              <th>Halten bis Schritt</th>
              <th>Hinweis</th>
            </tr>
          </thead>
          <tbody>
            {SERVO_OPTIONS.map(({ key, label }) => {
              const minStep = firstStepForServo(steps, key);
              return (
                <tr key={key}>
                  <td>{label}</td>
                  <td>
                    <input
                      type="number"
                      min={minStep ?? 1}
                      max={steps.length}
                      step={1}
                      value={holdUntil[key] ?? ""}
                      disabled={busy || minStep == null}
                      placeholder="—"
                      onChange={(e) => updateHold(key, e.target.value)}
                    />
                  </td>
                  <td className="muted">
                    {minStep == null
                      ? "Servo kommt in der Sequenz nicht vor"
                      : `min. ${minStep}, max. ${steps.length}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="servo-sequence-wrap">
        <table className="servo-sequence-table">
          <thead>
            <tr>
              <th>Schritt</th>
              <th>Servo</th>
              <th>Verfahrwert (°)</th>
              <th>Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((step, index) => {
              const limit = config.limits[step.servo];
              const current = status?.angles?.[step.servo];
              return (
                <tr key={index}>
                  <td>{index + 1}</td>
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
