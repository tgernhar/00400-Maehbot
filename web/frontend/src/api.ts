export interface BBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Detection {
  id: number;
  timestamp_ms: number;
  class_id: string;
  confidence: number;
  bbox: BBox;
  image_path: string | null;
  spray_scheduled: boolean;
  spray_blocked_reason: string | null;
  created_at: number;
}

export interface Status {
  test_mode: boolean;
  camera_healthy: boolean;
  tank_empty: boolean;
  tank_full: boolean;
  auth_enabled: boolean;
  latency: Record<string, number>;
}

export interface SprayConfig {
  delay_ms: number;
  duration_ms: number;
  camera_to_nozzle_mm: number;
  mower_speed_mm_s: number;
}

export interface ModeConfig {
  test_mode: boolean;
  min_confidence: number;
}

export interface TrainingSession {
  id: number;
  name: string;
  video_path: string;
  frame_count: number;
  created_at: number;
}

export interface PlantClass {
  id: string;
  name: string;
  sprayable: boolean;
}

const API = "/api";

export async function fetchStatus(): Promise<Status> {
  const r = await fetch(`${API}/status`);
  if (!r.ok) throw new Error("Status laden fehlgeschlagen");
  return r.json();
}

export async function fetchDetections(limit = 100): Promise<Detection[]> {
  const r = await fetch(`${API}/detections?limit=${limit}`);
  if (!r.ok) throw new Error("Erkennungen laden fehlgeschlagen");
  return r.json();
}

export async function fetchSprayConfig(): Promise<SprayConfig> {
  const r = await fetch(`${API}/config/spray`);
  if (!r.ok) throw new Error("Spray-Konfiguration laden fehlgeschlagen");
  return r.json();
}

export async function updateSprayConfig(cfg: Partial<SprayConfig>): Promise<SprayConfig> {
  const r = await fetch(`${API}/config/spray`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  if (!r.ok) throw new Error("Spray-Konfiguration speichern fehlgeschlagen");
  return r.json();
}

export async function fetchModeConfig(): Promise<ModeConfig> {
  const r = await fetch(`${API}/config/mode`);
  if (!r.ok) throw new Error("Modus-Konfiguration laden fehlgeschlagen");
  return r.json();
}

export async function updateModeConfig(cfg: Partial<ModeConfig>): Promise<ModeConfig> {
  const r = await fetch(`${API}/config/mode`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  if (!r.ok) throw new Error("Modus-Konfiguration speichern fehlgeschlagen");
  return r.json();
}

export async function fetchClasses(): Promise<PlantClass[]> {
  const r = await fetch(`${API}/classes`);
  if (!r.ok) throw new Error("Klassen laden fehlgeschlagen");
  return r.json();
}

export async function fetchTrainingSessions(): Promise<TrainingSession[]> {
  const r = await fetch(`${API}/training/sessions`);
  if (!r.ok) throw new Error("Sessions laden fehlgeschlagen");
  return r.json();
}

export async function uploadTrainingSession(name: string, file: File): Promise<TrainingSession> {
  const fd = new FormData();
  fd.append("name", name);
  fd.append("file", file);
  const r = await fetch(`${API}/training/sessions`, { method: "POST", body: fd });
  if (!r.ok) throw new Error("Session hochladen fehlgeschlagen");
  return r.json();
}

export function detectionImageUrl(id: number): string {
  return `${API}/detections/${id}/image`;
}

export function cameraPreviewUrl(cacheBust?: number): string {
  const q = cacheBust != null ? `?t=${cacheBust}` : "";
  return `${API}/camera/preview${q}`;
}

export function trainingFrameUrl(sessionId: number, frameIndex: number): string {
  return `${API}/training/sessions/${sessionId}/frames/${frameIndex}/image`;
}

export async function saveAnnotation(
  sessionId: number,
  frameIndex: number,
  classId: string,
  bbox: BBox
): Promise<void> {
  const r = await fetch(`${API}/training/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      frame_index: frameIndex,
      class_id: classId,
      bbox,
    }),
  });
  if (!r.ok) throw new Error("Annotation speichern fehlgeschlagen");
}

export async function exportYolo(sessionId: number): Promise<string> {
  const r = await fetch(`${API}/training/sessions/${sessionId}/export-yolo`, { method: "POST" });
  if (!r.ok) throw new Error("YOLO-Export fehlgeschlagen");
  const data = await r.json();
  return data.export_path;
}
