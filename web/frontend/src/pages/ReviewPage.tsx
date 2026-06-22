import { useEffect, useState } from "react";
import {
  Detection,
  cameraPreviewUrl,
  detectionImageUrl,
  fetchDetections,
  fetchStatus,
  Status,
} from "../api";

function BBoxOverlay({ detection }: { detection: Detection }) {
  const [dims, setDims] = useState({ w: 640, h: 480 });
  const url = detectionImageUrl(detection.id);

  return (
    <div className="bbox-container">
      <img
        src={url}
        alt="Erkennung"
        onLoad={(e) => {
          const img = e.currentTarget;
          setDims({ w: img.naturalWidth, h: img.naturalHeight });
        }}
      />
      <svg
        className="bbox-overlay"
        viewBox={`0 0 ${dims.w} ${dims.h}`}
        preserveAspectRatio="none"
      >
        <rect
          x={detection.bbox.x}
          y={detection.bbox.y}
          width={detection.bbox.width}
          height={detection.bbox.height}
          fill="none"
          stroke="#ff4444"
          strokeWidth="3"
        />
      </svg>
    </div>
  );
}

export default function ReviewPage() {
  const [detections, setDetections] = useState<Detection[]>([]);
  const [selected, setSelected] = useState<Detection | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewTick, setPreviewTick] = useState(0);

  useEffect(() => {
    fetchDetections()
      .then(setDetections)
      .catch((e) => setError(e.message));
    fetchStatus().then(setStatus).catch(() => undefined);
    const poll = setInterval(() => {
      fetchDetections().then(setDetections).catch(() => undefined);
      setPreviewTick(Date.now());
    }, 2000);
    return () => clearInterval(poll);
  }, []);

  return (
    <div>
      <h1>Erkennungen</h1>
      {error && <p className="error">{error}</p>}
      <div className="review-grid">
        <ul className="detection-list">
          {detections.length === 0 && (
            <li className="muted">Noch keine Erkennungen gespeichert.</li>
          )}
          {detections.map((d) => (
            <li
              key={d.id}
              className={selected?.id === d.id ? "active" : ""}
              onClick={() => setSelected(d)}
            >
              <img src={detectionImageUrl(d.id)} alt="" width={80} height={60} />
              <div>
                <strong>{d.class_id}</strong>
                <div>{(d.confidence * 100).toFixed(0)}%</div>
                <div className="muted">
                  {d.spray_scheduled ? "Sprühen geplant" : d.spray_blocked_reason ?? "—"}
                </div>
              </div>
            </li>
          ))}
        </ul>
        <div className="detail">
          {selected ? (
            <>
              <h2>Detail #{selected.id}</h2>
              <BBoxOverlay detection={selected} />
              <p>
                Klasse: {selected.class_id}, Confidence: {selected.confidence.toFixed(2)}
              </p>
            </>
          ) : (
            <>
              <h2>Live-Vorschau</h2>
              <img
                src={cameraPreviewUrl(previewTick)}
                alt="Kameravorschau"
                className="camera-preview"
                onError={(e) => {
                  e.currentTarget.style.display = "none";
                }}
              />
              <p className="muted">
                Erkennung auswählen oder warten, bis Unkräuter erkannt werden.
              </p>
            </>
          )}
        </div>
      </div>
      {status && (
        <p className="muted">
          Testmodus: {status.test_mode ? "an" : "aus"} | Kamera:{" "}
          {status.camera_healthy ? "OK" : "Fehler"}
        </p>
      )}
    </div>
  );
}
