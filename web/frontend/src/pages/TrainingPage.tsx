import { useEffect, useRef, useState } from "react";
import {
  BBox,
  cameraPreviewUrl,
  captureSnapshot,
  exportYolo,
  fetchClasses,
  fetchRecordingStatus,
  fetchTrainingSessions,
  pauseRecording,
  PlantClass,
  RecordingStatus,
  resumeRecording,
  saveAnnotation,
  startRecording,
  stopRecording,
  TrainingSession,
  trainingFrameUrl,
  uploadTrainingSession,
} from "../api";

function recordingLabel(status: RecordingStatus | null): string {
  if (!status) return "—";
  if (status.state === "recording") return `Aufnahme (${status.frame_count} Frames)`;
  if (status.state === "paused") return `Pausiert (${status.frame_count} Frames)`;
  return "Bereit";
}

export default function TrainingPage() {
  const [sessions, setSessions] = useState<TrainingSession[]>([]);
  const [classes, setClasses] = useState<PlantClass[]>([]);
  const [selectedSession, setSelectedSession] = useState<TrainingSession | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [classId, setClassId] = useState("clover");
  const [uploadName, setUploadName] = useState("");
  const [recordName, setRecordName] = useState("");
  const [recording, setRecording] = useState<RecordingStatus | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [previewTick, setPreviewTick] = useState(0);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const [previewBox, setPreviewBox] = useState<BBox | null>(null);

  async function refreshSessions(selectId?: number) {
    const list = await fetchTrainingSessions();
    setSessions(list);
    if (selectId != null) {
      const found = list.find((s) => s.id === selectId) ?? null;
      if (found) {
        setSelectedSession(found);
        setFrameIndex(0);
      }
    }
  }

  useEffect(() => {
    refreshSessions();
    fetchClasses().then((c) => {
      setClasses(c);
      if (c.length) setClassId(c[0].id);
    });
    fetchRecordingStatus().then(setRecording).catch(() => undefined);
    const poll = setInterval(() => {
      fetchRecordingStatus()
        .then(setRecording)
        .catch(() => undefined);
    }, 1000);
    return () => clearInterval(poll);
  }, []);

  useEffect(() => {
    if (!recording || (recording.state !== "recording" && recording.state !== "paused")) {
      return;
    }
    setPreviewTick(Date.now());
    const id = setInterval(() => setPreviewTick(Date.now()), 500);
    return () => clearInterval(id);
  }, [recording?.state]);

  useEffect(() => {
    drawFrame();
  }, [selectedSession, frameIndex]);

  function drawFrame() {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || !selectedSession) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (img.complete && img.naturalWidth) {
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      ctx.drawImage(img, 0, 0);
      if (previewBox) {
        ctx.strokeStyle = "#00ff88";
        ctx.lineWidth = 2;
        ctx.strokeRect(previewBox.x, previewBox.y, previewBox.width, previewBox.height);
      }
    }
  }

  async function handleUpload(file: File) {
    const session = await uploadTrainingSession(uploadName || file.name, file);
    setSessions((s) => [session, ...s]);
    setSelectedSession(session);
    setFrameIndex(0);
  }

  async function handleStartRecording() {
    const name = recordName.trim() || `Anlernfahrt_${new Date().toISOString().slice(0, 10)}`;
    try {
      const status = await startRecording(name);
      setRecording(status);
      setMessage("Aufnahme gestartet — Core verarbeitet den Befehl …");
      setTimeout(() => setMessage(null), 3000);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Start fehlgeschlagen");
    }
  }

  async function handlePauseRecording() {
    try {
      const status =
        recording?.state === "paused" ? await resumeRecording() : await pauseRecording();
      setRecording(status);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Pause fehlgeschlagen");
    }
  }

  async function handleStopRecording() {
    try {
      await stopRecording();
      for (let i = 0; i < 10; i += 1) {
        await new Promise((r) => setTimeout(r, 500));
        const status = await fetchRecordingStatus();
        setRecording(status);
        if (status.state === "idle" && status.session_id != null) {
          await refreshSessions(status.session_id);
          setMessage(`Aufnahme gespeichert (${status.frame_count} Frames)`);
          setTimeout(() => setMessage(null), 4000);
          return;
        }
        if (status.error) {
          setMessage(status.error);
          return;
        }
      }
      setMessage("Stopp gesendet — Status bitte prüfen");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Stopp fehlgeschlagen");
    }
  }

  async function handleCaptureSnapshot() {
    const name =
      recordName.trim() ||
      `Foto_${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}`;
    try {
      await captureSnapshot(name);
      // #region agent log
      fetch("http://127.0.0.1:7350/ingest/6180ef00-058c-42a8-86a0-0e6278a26d8a", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "bc4e4e" },
        body: JSON.stringify({
          sessionId: "bc4e4e",
          runId: "ui",
          hypothesisId: "H2",
          location: "TrainingPage.tsx:handleCaptureSnapshot",
          message: "snapshot API accepted",
          data: { name },
          timestamp: Date.now(),
        }),
      }).catch(() => {});
      // #endregion
      for (let i = 0; i < 10; i += 1) {
        await new Promise((r) => setTimeout(r, 500));
        const status = await fetchRecordingStatus();
        setRecording(status);
        if (status.session_id != null && status.frame_count >= 1) {
          await refreshSessions(status.session_id);
          setMessage("Foto gespeichert — Annotation möglich");
          setTimeout(() => setMessage(null), 4000);
          return;
        }
        if (status.error) {
          setMessage(status.error);
          return;
        }
      }
      setMessage("Foto-Befehl gesendet — Status bitte prüfen");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Foto fehlgeschlagen");
    }
  }

  function pointerPos(e: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    };
  }

  async function saveBox(box: BBox) {
    if (!selectedSession) return;
    await saveAnnotation(selectedSession.id, frameIndex, classId, box);
    setMessage("Annotation gespeichert");
    setPreviewBox(null);
    setTimeout(() => setMessage(null), 2000);
  }

  const isRecording = recording?.state === "recording" || recording?.state === "paused";

  return (
    <div>
      <h1>Training / Anlernen</h1>
      {message && <p className="ok">{message}</p>}
      {recording?.error && <p className="error">{recording.error}</p>}

      <section className="recording-panel">
        <h2>Anlernfahrt aufnehmen</h2>
        <p className="muted">
          Start während der Fahrt — der Core speichert Kamerabilder als Video. Pause unterbricht
          die Aufnahme, Stopp legt die Session an. Alternativ ein Einzelfoto mit dem Kamera-Button.
        </p>
        <div className="recording-controls">
          <input
            placeholder="Name der Anlernfahrt"
            value={recordName}
            onChange={(e) => setRecordName(e.target.value)}
            disabled={isRecording}
          />
          <button type="button" disabled={isRecording} onClick={handleStartRecording}>
            Start
          </button>
          <button
            type="button"
            className="icon-btn"
            disabled={isRecording}
            onClick={handleCaptureSnapshot}
            title="Einzelfoto aufnehmen"
            aria-label="Einzelfoto aufnehmen"
          >
            📷
          </button>
          <button
            type="button"
            disabled={!isRecording}
            onClick={handlePauseRecording}
          >
            {recording?.state === "paused" ? "Fortsetzen" : "Pause"}
          </button>
          <button type="button" disabled={!isRecording} onClick={handleStopRecording}>
            Stopp
          </button>
          <span className={`badge ${isRecording ? "warn" : "ok"}`}>{recordingLabel(recording)}</span>
        </div>
        {isRecording && (
          <div className="recording-live">
            <p className="muted">Livebild während der Aufnahme</p>
            <img
              src={cameraPreviewUrl(previewTick)}
              alt="Livebild"
              className="camera-preview"
              onError={(e) => {
                e.currentTarget.style.opacity = "0.35";
              }}
            />
          </div>
        )}
      </section>

      <div className="training-upload">
        <span className="muted">Oder Video hochladen:</span>
        <input placeholder="Session-Name" value={uploadName} onChange={(e) => setUploadName(e.target.value)} />
        <input
          type="file"
          accept="video/*"
          onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
        />
      </div>
      <div className="training-layout">
        <ul className="session-list">
          {sessions.map((s) => (
            <li
              key={s.id}
              className={selectedSession?.id === s.id ? "active" : ""}
              onClick={() => {
                setSelectedSession(s);
                setFrameIndex(0);
              }}
            >
              {s.name} ({s.frame_count} Frames)
            </li>
          ))}
        </ul>
        {selectedSession && (
          <div>
            <div className="frame-controls">
              <button disabled={frameIndex <= 0} onClick={() => setFrameIndex((f) => f - 1)}>
                Zurück
              </button>
              <span>Frame {frameIndex}</span>
              <button
                disabled={frameIndex >= selectedSession.frame_count - 1}
                onClick={() => setFrameIndex((f) => f + 1)}
              >
                Vor
              </button>
              <select value={classId} onChange={(e) => setClassId(e.target.value)}>
                {classes.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <button onClick={() => exportYolo(selectedSession.id).then(setMessage)}>
                YOLO exportieren
              </button>
            </div>
            <img
              ref={imgRef}
              src={trainingFrameUrl(selectedSession.id, frameIndex)}
              alt="Frame"
              className="hidden-img"
              onLoad={drawFrame}
            />
            <canvas
              ref={canvasRef}
              className="training-canvas"
              onMouseDown={(e) => {
                dragStart.current = pointerPos(e);
              }}
              onMouseMove={(e) => {
                if (!dragStart.current) return;
                const p = pointerPos(e);
                const x = Math.min(dragStart.current.x, p.x);
                const y = Math.min(dragStart.current.y, p.y);
                setPreviewBox({
                  x,
                  y,
                  width: Math.abs(p.x - dragStart.current.x),
                  height: Math.abs(p.y - dragStart.current.y),
                });
                drawFrame();
              }}
              onMouseUp={(e) => {
                if (!dragStart.current) return;
                const p = pointerPos(e);
                const box: BBox = {
                  x: Math.min(dragStart.current.x, p.x),
                  y: Math.min(dragStart.current.y, p.y),
                  width: Math.abs(p.x - dragStart.current.x),
                  height: Math.abs(p.y - dragStart.current.y),
                };
                dragStart.current = null;
                if (box.width > 4 && box.height > 4) saveBox(box);
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
