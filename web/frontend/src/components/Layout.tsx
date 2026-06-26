import { Link } from "react-router-dom";
import { Status } from "../api";

export function StatusBanner({ status }: { status: Status | null }) {
  if (!status) return null;
  return (
    <div className="status-banner">
      {status.test_mode && <span className="badge warn">Testmodus – kein Sprühen</span>}
      {!status.auth_enabled && <span className="badge info">Auth deaktiviert</span>}
      {status.tank_empty && <span className="badge error">Tank leer</span>}
      {status.camera_healthy ? (
        <span className="badge ok">Kamera OK</span>
      ) : (
        <span className="badge error">Kamera nicht bereit</span>
      )}
      {status.latency.avg_frame_to_detect_ms > 0 && (
        <span className="badge">
          Latenz Detektion: {status.latency.avg_frame_to_detect_ms.toFixed(1)} ms
        </span>
      )}
    </div>
  );
}

export function Nav() {
  return (
    <nav className="nav">
      <strong>Maehbot</strong>
      <Link to="/">Review</Link>
      <Link to="/drive">Fahren</Link>
      <Link to="/settings">Spray-Einstellungen</Link>
      <Link to="/training">Training</Link>
    </nav>
  );
}
