import { useEffect, useRef, useState } from "react";
import {
  BBox,
  exportYolo,
  fetchClasses,
  fetchTrainingSessions,
  PlantClass,
  saveAnnotation,
  TrainingSession,
  trainingFrameUrl,
  uploadTrainingSession,
} from "../api";

export default function TrainingPage() {
  const [sessions, setSessions] = useState<TrainingSession[]>([]);
  const [classes, setClasses] = useState<PlantClass[]>([]);
  const [selectedSession, setSelectedSession] = useState<TrainingSession | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [classId, setClassId] = useState("clover");
  const [uploadName, setUploadName] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const [previewBox, setPreviewBox] = useState<BBox | null>(null);

  useEffect(() => {
    fetchTrainingSessions().then(setSessions);
    fetchClasses().then((c) => {
      setClasses(c);
      if (c.length) setClassId(c[0].id);
    });
  }, []);

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

  return (
    <div>
      <h1>Training / Anlernen</h1>
      {message && <p className="ok">{message}</p>}
      <div className="training-upload">
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
