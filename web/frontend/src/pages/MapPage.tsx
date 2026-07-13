import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchMapMeta,
  fetchNavStatus,
  fetchNavigationConfig,
  fetchZones,
  MapMeta,
  mapImageUrl,
  mowZone,
  NavigationConfig,
  navGoto,
  navStop,
  NavStatus,
  resetMap,
  saveMap,
  saveZones,
  updateNavigationConfig,
  Zone,
} from "../api";

const MAP_REFRESH_MS = 2000;
const STATUS_REFRESH_MS = 1000;

const NAV_STATE_LABELS: Record<NavStatus["state"], string> = {
  idle: "Bereit",
  turning: "dreht",
  driving: "fährt",
  done: "Ziel erreicht",
  aborted: "abgebrochen",
};

type EditorMode = "navigate" | "zone";

interface DraftRect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export default function MapPage() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  const [meta, setMeta] = useState<MapMeta | null>(null);
  const [nav, setNav] = useState<NavStatus | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [navConfig, setNavConfig] = useState<NavigationConfig | null>(null);
  const [mode, setMode] = useState<EditorMode>("navigate");
  const [draft, setDraft] = useState<DraftRect | null>(null);
  const [mapAvailable, setMapAvailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [redraw, setRedraw] = useState(0);

  const flash = (text: string) => {
    setMessage(text);
    setTimeout(() => setMessage(null), 3000);
  };

  // -- polling -------------------------------------------------------------

  useEffect(() => {
    fetchMapMeta().then(setMeta).catch(() => undefined);
    fetchZones().then(setZones).catch(() => undefined);
    fetchNavigationConfig().then(setNavConfig).catch(() => undefined);
    fetchNavStatus().then(setNav).catch(() => undefined);
    const t = setInterval(() => {
      fetchNavStatus().then(setNav).catch(() => undefined);
    }, STATUS_REFRESH_MS);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const load = () => {
      const img = new Image();
      img.onload = () => {
        imgRef.current = img;
        setMapAvailable(true);
        setRedraw((n) => n + 1);
      };
      img.onerror = () => undefined;
      img.src = mapImageUrl(Date.now());
    };
    load();
    const t = setInterval(load, MAP_REFRESH_MS);
    return () => clearInterval(t);
  }, []);

  // -- coordinate transforms ---------------------------------------------------

  const pxPerMeter = meta ? meta.size_pixels / meta.size_meters : 1;
  const toPx = useCallback(
    (m: number) => m * pxPerMeter,
    [pxPerMeter]
  );

  const eventToMeters = useCallback(
    (e: { clientX: number; clientY: number }): [number, number] | null => {
      const canvas = canvasRef.current;
      if (!canvas || !meta) return null;
      const rect = canvas.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * meta.size_pixels;
      const y = ((e.clientY - rect.top) / rect.height) * meta.size_pixels;
      return [x / pxPerMeter, y / pxPerMeter];
    },
    [meta, pxPerMeter]
  );

  // -- rendering -----------------------------------------------------------------

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !meta) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const size = meta.size_pixels;
    canvas.width = size;
    canvas.height = size;

    ctx.fillStyle = "#0a0e12";
    ctx.fillRect(0, 0, size, size);
    if (imgRef.current) {
      ctx.drawImage(imgRef.current, 0, 0, size, size);
    }

    // Zones
    for (const zone of zones) {
      drawZone(ctx, zone, toPx);
    }

    // Draft zone rectangle while dragging
    if (draft) {
      ctx.strokeStyle = "#7eb8ff";
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 2;
      ctx.strokeRect(
        toPx(Math.min(draft.x0, draft.x1)),
        toPx(Math.min(draft.y0, draft.y1)),
        toPx(Math.abs(draft.x1 - draft.x0)),
        toPx(Math.abs(draft.y1 - draft.y0))
      );
      ctx.setLineDash([]);
    }

    // Planned path
    if (nav && nav.waypoints.length > 0 && nav.x_m != null && nav.y_m != null) {
      ctx.strokeStyle = "#f0c674";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(toPx(nav.x_m), toPx(nav.y_m));
      for (const [wx, wy] of nav.waypoints) {
        ctx.lineTo(toPx(wx), toPx(wy));
      }
      ctx.stroke();
    }

    // Target marker
    if (nav && nav.target_x_m != null && nav.target_y_m != null) {
      const tx = toPx(nav.target_x_m);
      const ty = toPx(nav.target_y_m);
      ctx.strokeStyle = "#ff8866";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(tx - 8, ty);
      ctx.lineTo(tx + 8, ty);
      ctx.moveTo(tx, ty - 8);
      ctx.lineTo(tx, ty + 8);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(tx, ty, 10, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Robot pose
    if (nav && nav.x_m != null && nav.y_m != null && nav.theta_deg != null) {
      const rx = toPx(nav.x_m);
      const ry = toPx(nav.y_m);
      const theta = (nav.theta_deg * Math.PI) / 180;
      ctx.fillStyle = "#59d98c";
      ctx.strokeStyle = "#59d98c";
      ctx.beginPath();
      ctx.arc(rx, ry, 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(rx, ry);
      ctx.lineTo(rx + Math.cos(theta) * 18, ry + Math.sin(theta) * 18);
      ctx.stroke();
    }
  }, [meta, nav, zones, draft, toPx, redraw]);

  // -- interactions ------------------------------------------------------------------

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (mode !== "zone") return;
    const pos = eventToMeters(e);
    if (!pos) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDraft({ x0: pos[0], y0: pos[1], x1: pos[0], y1: pos[1] });
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (mode !== "zone" || !draft) return;
    const pos = eventToMeters(e);
    if (!pos) return;
    setDraft({ ...draft, x1: pos[0], y1: pos[1] });
  };

  const onPointerUp = async (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (mode === "navigate") {
      const pos = eventToMeters(e);
      if (!pos) return;
      setError(null);
      try {
        setNav(await navGoto(pos[0], pos[1]));
        flash(`Fahre zu (${pos[0].toFixed(2)} m, ${pos[1].toFixed(2)} m)`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Fehler");
      }
      return;
    }
    if (!draft) return;
    const width = Math.abs(draft.x1 - draft.x0);
    const height = Math.abs(draft.y1 - draft.y0);
    setDraft(null);
    if (width < 0.2 || height < 0.2) return; // ignore tiny accidental drags
    const zone: Zone = {
      id: `z${Date.now()}`,
      name: `Zone ${zones.length + 1}`,
      x_m: Math.min(draft.x0, draft.x1),
      y_m: Math.min(draft.y0, draft.y1),
      width_m: width,
      height_m: height,
      direction_deg: 0,
    };
    const next = [...zones, zone];
    setZones(next);
    try {
      await saveZones(next);
      flash(`Zone „${zone.name}" angelegt`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  };

  const updateZone = (id: string, patch: Partial<Zone>) => {
    setZones((prev) => prev.map((z) => (z.id === id ? { ...z, ...patch } : z)));
  };

  const persistZones = async () => {
    setError(null);
    try {
      await saveZones(zones);
      flash("Zonen gespeichert");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  };

  const removeZone = async (id: string) => {
    const next = zones.filter((z) => z.id !== id);
    setZones(next);
    try {
      await saveZones(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  };

  const handleMow = async (id: string) => {
    setError(null);
    try {
      setNav(await mowZone(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  };

  const handleStop = async () => {
    setError(null);
    try {
      setNav(await navStop());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  };

  const handleSaveMap = async () => {
    setError(null);
    try {
      await saveMap();
      flash("Karte gespeichert");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  };

  const handleResetMap = async () => {
    if (!window.confirm("Karte wirklich zurücksetzen? Die gespeicherte Karte wird gelöscht.")) {
      return;
    }
    setError(null);
    try {
      await resetMap();
      flash("Karte zurückgesetzt");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  };

  async function saveNavConfig() {
    if (!navConfig) return;
    setError(null);
    try {
      setNavConfig(await updateNavigationConfig(navConfig));
      flash("Navigationsparameter gespeichert");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  }

  const navActive = nav?.state === "turning" || nav?.state === "driving";

  const numberField = (
    label: string,
    key: keyof NavigationConfig,
    step: number
  ) =>
    navConfig && (
      <label>
        {label}
        <input
          type="number"
          step={step}
          min={0}
          value={navConfig[key]}
          onChange={(e) => setNavConfig({ ...navConfig, [key]: Number(e.target.value) })}
        />
      </label>
    );

  return (
    <div>
      <h1>Karte</h1>
      <p className="muted">
        Beim Fahren erzeugt der LiDAR eine Karte der Umgebung (SLAM). Klick auf die Karte
        schickt den Roboter dorthin; im Zonen-Modus ziehst du Rechtecke auf, die in Bahnen
        gemäht werden können.
      </p>
      {error && <p className="error">{error}</p>}
      {message && <p className="ok">{message}</p>}
      {nav && !nav.slam_available && (
        <p className="warn">
          Kartierung nicht verfügbar — BreezySLAM ist auf dem Fahr-Knoten nicht installiert
          (siehe docs/mapping-navigation.md).
        </p>
      )}

      <div className="drive-status-row">
        <span className={`badge ${navActive ? "ok" : ""}`}>
          {nav ? NAV_STATE_LABELS[nav.state] : "–"}
        </span>
        {nav?.mode === "mow" && nav.line_count > 0 && (
          <span className="badge">
            Bahn {Math.min(nav.line_index + 1, nav.line_count)} / {nav.line_count}
            {nav.zone_name ? ` (${nav.zone_name})` : ""}
          </span>
        )}
        {nav?.x_m != null && nav?.y_m != null && (
          <span className="badge">
            Position: {nav.x_m.toFixed(2)} m / {nav.y_m.toFixed(2)} m
            {nav.theta_deg != null ? ` @ ${nav.theta_deg.toFixed(0)}°` : ""}
          </span>
        )}
        <span className={`badge ${nav?.lidar_connected ? "ok" : "warn"}`}>
          {nav?.lidar_connected ? "LiDAR verbunden" : "LiDAR nicht verbunden"}
        </span>
      </div>

      <div className="map-toolbar">
        <button
          type="button"
          className={mode === "navigate" ? "active" : ""}
          onClick={() => setMode("navigate")}
        >
          Ziel wählen
        </button>
        <button
          type="button"
          className={mode === "zone" ? "active" : ""}
          onClick={() => setMode("zone")}
        >
          Zone zeichnen
        </button>
        {navActive && (
          <button type="button" className="danger-btn" onClick={handleStop}>
            Fahrt stoppen
          </button>
        )}
        <span className="map-toolbar-spacer" />
        <button type="button" onClick={handleSaveMap}>
          Karte speichern
        </button>
        <button type="button" className="danger-btn" onClick={handleResetMap}>
          Karte zurücksetzen
        </button>
      </div>

      <div className="map-canvas-wrap">
        <canvas
          ref={canvasRef}
          className={`map-canvas ${mode === "zone" ? "zone-mode" : ""}`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onContextMenu={(e) => e.preventDefault()}
        />
        {!mapAvailable && (
          <div className="drive-preview-placeholder map-placeholder">
            <p className="muted">
              Noch keine Karte — fahre den Roboter ein Stück, damit der LiDAR die Umgebung
              erfassen kann.
            </p>
          </div>
        )}
      </div>

      <div className="coverage-panel">
        <h2>Zonen</h2>
        {zones.length === 0 ? (
          <p className="muted">
            Noch keine Zonen. Wähle „Zone zeichnen" und ziehe ein Rechteck auf der Karte auf.
          </p>
        ) : (
          <table className="zones-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Größe</th>
                <th>Bearbeitungsrichtung (°)</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {zones.map((zone) => (
                <tr key={zone.id}>
                  <td>
                    <input
                      type="text"
                      value={zone.name}
                      onChange={(e) => updateZone(zone.id, { name: e.target.value })}
                    />
                  </td>
                  <td>
                    {zone.width_m.toFixed(1)} × {zone.height_m.toFixed(1)} m
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0}
                      max={359}
                      step={5}
                      value={zone.direction_deg}
                      onChange={(e) =>
                        updateZone(zone.id, {
                          direction_deg: ((Number(e.target.value) % 360) + 360) % 360,
                        })
                      }
                    />
                  </td>
                  <td className="zones-actions">
                    <button
                      type="button"
                      disabled={navActive}
                      onClick={() => handleMow(zone.id)}
                    >
                      Zone mähen
                    </button>
                    <button
                      type="button"
                      className="danger-btn"
                      onClick={() => removeZone(zone.id)}
                    >
                      Löschen
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {zones.length > 0 && (
          <button type="button" onClick={persistZones}>
            Zonen speichern
          </button>
        )}
      </div>

      {navConfig && (
        <div className="coverage-panel">
          <h2>Navigationsparameter</h2>
          <div className="coverage-grid">
            {numberField("Kettentempo geradeaus (0–1)", "drive_speed", 0.05)}
            {numberField("Kettentempo drehen (0–1)", "turn_speed", 0.05)}
            {numberField("Wegpunkt-Toleranz (m)", "waypoint_tolerance_m", 0.05)}
            {numberField("Kurs-Toleranz (°)", "heading_tolerance_deg", 1)}
            {numberField("Hindernis-Stoppdistanz (m)", "obstacle_stop_m", 0.05)}
            {numberField("Hindernis-Sektor (°)", "obstacle_sector_deg", 5)}
            {numberField("Roboter-Radius (m)", "robot_radius_m", 0.05)}
            {numberField("Bahnabstand (m)", "line_spacing_m", 0.05)}
            {numberField("Max. Neuplanungen", "max_replans", 1)}
          </div>
          <button type="button" onClick={saveNavConfig}>
            Navigationsparameter speichern
          </button>
        </div>
      )}
    </div>
  );
}

/** Draw a zone rectangle with a preview of the mowing line direction. */
function drawZone(
  ctx: CanvasRenderingContext2D,
  zone: Zone,
  toPx: (m: number) => number
) {
  const x = toPx(zone.x_m);
  const y = toPx(zone.y_m);
  const w = toPx(zone.width_m);
  const h = toPx(zone.height_m);

  ctx.fillStyle = "rgba(126, 184, 255, 0.12)";
  ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = "#7eb8ff";
  ctx.lineWidth = 2;
  ctx.strokeRect(x, y, w, h);

  // Mowing direction preview: parallel lines clipped to the rectangle
  const theta = (zone.direction_deg * Math.PI) / 180;
  const dx = Math.cos(theta);
  const dy = Math.sin(theta);
  const nx = -dy;
  const ny = dx;
  const cx = x + w / 2;
  const cy = y + h / 2;
  const diag = Math.sqrt(w * w + h * h);
  const spacing = Math.max(12, diag / 10);

  ctx.save();
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.clip();
  ctx.strokeStyle = "rgba(126, 184, 255, 0.35)";
  ctx.lineWidth = 1;
  for (let s = -diag / 2; s <= diag / 2; s += spacing) {
    ctx.beginPath();
    ctx.moveTo(cx + nx * s - dx * diag, cy + ny * s - dy * diag);
    ctx.lineTo(cx + nx * s + dx * diag, cy + ny * s + dy * diag);
    ctx.stroke();
  }
  ctx.restore();

  ctx.fillStyle = "#c9dcf5";
  ctx.font = "13px sans-serif";
  ctx.fillText(zone.name, x + 6, y + 16);
}
