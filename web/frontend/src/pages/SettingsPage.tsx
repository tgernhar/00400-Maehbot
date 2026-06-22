import { FormEvent, useEffect, useState } from "react";
import {
  fetchModeConfig,
  fetchSprayConfig,
  fetchStatus,
  ModeConfig,
  SprayConfig,
  Status,
  updateModeConfig,
  updateSprayConfig,
} from "../api";

export default function SettingsPage() {
  const [spray, setSpray] = useState<SprayConfig | null>(null);
  const [mode, setMode] = useState<ModeConfig | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSprayConfig().then(setSpray);
    fetchModeConfig().then(setMode);
    fetchStatus().then(setStatus);
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!spray || !mode) return;
    setError(null);
    try {
      await updateSprayConfig(spray);
      await updateModeConfig(mode);
      setMessage("Einstellungen gespeichert");
      setTimeout(() => setMessage(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  }

  if (!spray || !mode) return <p>Laden…</p>;

  return (
    <div>
      <h1>Spray-Einstellungen</h1>
      {status?.test_mode && (
        <p className="warn">Testmodus aktiv – Düse wird nicht ausgelöst.</p>
      )}
      {message && <p className="ok">{message}</p>}
      {error && <p className="error">{error}</p>}
      <form onSubmit={onSubmit} className="form-grid">
        <label>
          Verzögerung (ms)
          <input
            type="number"
            value={spray.delay_ms}
            onChange={(e) => setSpray({ ...spray, delay_ms: Number(e.target.value) })}
          />
        </label>
        <label>
          Auslösedauer (ms)
          <input
            type="number"
            value={spray.duration_ms}
            onChange={(e) => setSpray({ ...spray, duration_ms: Number(e.target.value) })}
          />
        </label>
        <label>
          Abstand Kamera–Düse (mm)
          <input
            type="number"
            value={spray.camera_to_nozzle_mm}
            onChange={(e) =>
              setSpray({ ...spray, camera_to_nozzle_mm: Number(e.target.value) })
            }
          />
        </label>
        <label>
          Geschwindigkeit (mm/s)
          <input
            type="number"
            value={spray.mower_speed_mm_s}
            onChange={(e) => setSpray({ ...spray, mower_speed_mm_s: Number(e.target.value) })}
          />
        </label>
        <label>
          Min. Confidence
          <input
            type="number"
            step="0.01"
            min="0"
            max="1"
            value={mode.min_confidence}
            onChange={(e) => setMode({ ...mode, min_confidence: Number(e.target.value) })}
          />
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={mode.test_mode}
            onChange={(e) => setMode({ ...mode, test_mode: e.target.checked })}
          />
          Testmodus (nur markieren)
        </label>
        <button type="submit">Speichern</button>
      </form>
    </div>
  );
}
