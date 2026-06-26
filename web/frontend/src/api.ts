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

export interface DriveStatus {
  left: number;
  right: number;
  enabled: boolean;
  moving: boolean;
  max_speed: number;
  error: string | null;
}

export interface DriveConfig {
  enabled: boolean;
  max_speed: number;
  watchdog_timeout_ms: number;
  invert_left: boolean;
  invert_right: boolean;
}

export interface TrainingSession {
  id: number;
  name: string;
  video_path: string;
  frame_count: number;
  created_at: number;
}

export interface RecordingStatus {
  state: "idle" | "recording" | "paused";
  session_name: string;
  frame_count: number;
  session_id: number | null;
  error: string | null;
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

export async function fetchDriveConfig(): Promise<DriveConfig> {
  const r = await fetch(`${API}/config/drive`);
  if (!r.ok) throw new Error("Fahr-Konfiguration laden fehlgeschlagen");
  return r.json();
}

export async function updateDriveConfig(cfg: Partial<DriveConfig>): Promise<DriveConfig> {
  const r = await fetch(`${API}/config/drive`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  if (!r.ok) throw new Error("Fahr-Konfiguration speichern fehlgeschlagen");
  return r.json();
}

export async function fetchDriveStatus(): Promise<DriveStatus> {
  const r = await fetch(`${API}/drive/status`);
  if (!r.ok) throw new Error("Fahrstatus laden fehlgeschlagen");
  return r.json();
}

export async function sendDriveCommand(left: number, right: number): Promise<DriveStatus> {
  const r = await fetch(`${API}/drive/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ left, right }),
  });
  if (!r.ok) throw new Error("Fahrbefehl fehlgeschlagen");
  return r.json();
}

export async function stopDrive(): Promise<DriveStatus> {
  const r = await fetch(`${API}/drive/stop`, { method: "POST" });
  if (!r.ok) throw new Error("Stopp fehlgeschlagen");
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

export async function fetchRecordingStatus(): Promise<RecordingStatus> {
  const r = await fetch(`${API}/training/record/status`);
  if (!r.ok) throw new Error("Aufnahmestatus laden fehlgeschlagen");
  return r.json();
}

export async function startRecording(name: string): Promise<RecordingStatus> {
  const r = await fetch(`${API}/training/record/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail ?? "Aufnahme starten fehlgeschlagen");
  }
  return r.json();
}

export async function pauseRecording(): Promise<RecordingStatus> {
  const r = await fetch(`${API}/training/record/pause`, { method: "POST" });
  if (!r.ok) throw new Error("Pause fehlgeschlagen");
  return r.json();
}

export async function resumeRecording(): Promise<RecordingStatus> {
  const r = await fetch(`${API}/training/record/resume`, { method: "POST" });
  if (!r.ok) throw new Error("Fortsetzen fehlgeschlagen");
  return r.json();
}

export async function stopRecording(): Promise<RecordingStatus> {
  const r = await fetch(`${API}/training/record/stop`, { method: "POST" });
  if (!r.ok) throw new Error("Stopp fehlgeschlagen");
  return r.json();
}

export async function captureSnapshot(name: string): Promise<RecordingStatus> {
  const r = await fetch(`${API}/training/record/snapshot`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail ?? "Foto aufnehmen fehlgeschlagen");
  }
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

export async function deleteTrainingSession(sessionId: number): Promise<void> {
  const r = await fetch(`${API}/training/sessions/${sessionId}`, { method: "DELETE" });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail ?? "Session löschen fehlgeschlagen");
  }
}

export interface SessionAnnotation {
  id: number;
  session_id: number;
  frame_index: number;
  class_id: string;
  bbox: BBox;
}

export async function fetchSessionAnnotations(sessionId: number): Promise<SessionAnnotation[]> {
  const r = await fetch(`${API}/training/sessions/${sessionId}/annotations`);
  if (!r.ok) throw new Error("Annotationen laden fehlgeschlagen");
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
): Promise<SessionAnnotation> {
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
  return r.json();
}

export interface YoloExportResult {
  export_path: string;
  image_count: number;
  label_count: number;
  annotation_count: number;
}

export async function exportYolo(sessionId: number): Promise<YoloExportResult> {
  const r = await fetch(`${API}/training/sessions/${sessionId}/export-yolo`, { method: "POST" });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail ?? "YOLO-Export fehlgeschlagen");
  }
  return r.json();
}
