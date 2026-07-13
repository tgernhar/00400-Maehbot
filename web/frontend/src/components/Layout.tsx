import { Link } from "react-router-dom";
import { Status } from "../api";

export function StatusBanner({ status }: { status: Status | null }) {
  if (!status) return null;
  // Spray/tank/test-mode state only exists when a vision node is present
  const visionState = status.role !== "drive" || status.vision_connected;
  return (
    <div className="status-banner">
      {status.role === "drive" && (
        <span className="badge info">Fahr-Knoten</span>
      )}
      {status.role === "vision" && (
        <span className="badge info">Vision-Knoten</span>
      )}
      {status.role === "drive" && !status.vision_connected && (
        <span className="badge warn">Vision-Knoten nicht verbunden</span>
      )}
      {visionState && status.test_mode && (
        <span className="badge warn">Testmodus – kein Sprühen</span>
      )}
      {!status.auth_enabled && <span className="badge info">Auth deaktiviert</span>}
      {visionState && status.tank_empty && <span className="badge error">Tank leer</span>}
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
      <Link to="/map">Karte</Link>
      <Link to="/spray">Sprühen</Link>
      <Link to="/settings">Spray-Einstellungen</Link>
      <Link to="/training">Training</Link>
    </nav>
  );
}
