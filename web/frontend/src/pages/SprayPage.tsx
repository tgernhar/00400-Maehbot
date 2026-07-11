import { useEffect, useState } from "react";
import {
  fetchServoConfig,
  fetchServoStatus,
  ServoAngles,
  ServoConfig,
  ServoStatus,
  startServoHome,
  startServoTest,
} from "../api";

const SERVOS: { key: keyof ServoAngles; label: string; description: string }[] = [
  {
    key: "position",
    label: "Servo 1 – Positionierung",
    description: "Drehwinkel der Düse",
  },
  {
    key: "tension",
    label: "Servo 2 – Spannservo",
    description: "Druck für das Sprühen",
  },
  {
    key: "trigger",
    label: "Servo 3 – Betätigung",
    description: "Auslösemechanismus",
  },
];

const STATE_LABELS: Record<ServoStatus["state"], string> = {
  idle: "Bereit",
  homing: "Grundstellung wird angefahren…",
  testing: "Testlauf läuft…",
};

export default function SprayPage() {
  const [config, setConfig] = useState<ServoConfig | null>(null);
  const [angles, setAngles] = useState<ServoAngles | null>(null);
  const [status, setStatus] = useState<ServoStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const busy = status != null && status.state !== "idle";

  useEffect(() => {
    fetchServoConfig()
      .then((cfg) => {
        setConfig(cfg);
        setAngles(cfg.test_angles);
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

  async function onTest() {
    if (!angles) return;
    setError(null);
    setMessage(null);
    try {
      setStatus(await startServoTest(angles));
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

  if (!config || !angles) {
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
        Servo-Testlauf: Der Ablauf fährt zuerst die eingestellten Winkel an und
        kehrt danach automatisch in die Grundstellung zurück.
      </p>
      {status && (
        <p className={busy ? "warn" : "ok"}>
          Status: {STATE_LABELS[status.state] ?? status.state}
        </p>
      )}
      {status?.error && <p className="error">{status.error}</p>}
      {message && <p className="ok">{message}</p>}
      {error && <p className="error">{error}</p>}
      <div className="servo-grid">
        {SERVOS.map(({ key, label, description }) => {
          const limit = config.limits[key];
          const current = status?.angles?.[key];
          return (
            <div className="servo-card" key={key}>
              <h2>{label}</h2>
              <p className="muted">{description}</p>
              <div className="servo-slider-row">
                <input
                  type="range"
                  min={limit.min_angle}
                  max={limit.max_angle}
                  step={1}
                  value={angles[key]}
                  disabled={busy}
                  onChange={(e) =>
                    setAngles({ ...angles, [key]: Number(e.target.value) })
                  }
                />
                <input
                  type="number"
                  min={limit.min_angle}
                  max={limit.max_angle}
                  value={angles[key]}
                  disabled={busy}
                  onChange={(e) =>
                    setAngles({ ...angles, [key]: Number(e.target.value) })
                  }
                />
                <span>°</span>
              </div>
              <p className="muted servo-range">
                Bereich: {limit.min_angle}° bis {limit.max_angle}°
                {current != null && ` — Aktuell: ${current}°`}
              </p>
            </div>
          );
        })}
      </div>
      <div className="servo-actions">
        <button onClick={onTest} disabled={busy}>
          Testen
        </button>
        <button onClick={onHome} disabled={busy}>
          Grundstellung anfahren
        </button>
      </div>
    </div>
  );
}
