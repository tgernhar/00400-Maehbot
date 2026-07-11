import { PointerEvent as ReactPointerEvent, useCallback, useRef, useState } from "react";

type Props = {
  /** Called once when the user grabs the joystick. */
  onStart: () => void;
  /** Called continuously with tank track speeds in -1..1 while dragging. */
  onChange: (left: number, right: number) => void;
  /** Called when the user releases (robot should stop). */
  onEnd: () => void;
  disabled?: boolean;
};

/**
 * Touch joystick that merges direction and speed into one control:
 * the drag direction sets the driving direction, the distance from the
 * center sets the speed. The (x, y) vector is mixed into differential
 * (left/right) track speeds via arcade mixing.
 */
export default function DriveJoystick({ onStart, onChange, onEnd, disabled }: Props) {
  const baseRef = useRef<HTMLDivElement | null>(null);
  const [knob, setKnob] = useState({ x: 0, y: 0 });
  const active = useRef(false);

  const compute = useCallback(
    (clientX: number, clientY: number) => {
      const el = baseRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const radius = rect.width / 2;
      let dx = clientX - cx;
      let dy = clientY - cy;
      const dist = Math.hypot(dx, dy);
      if (dist > radius) {
        dx = (dx / dist) * radius;
        dy = (dy / dist) * radius;
      }
      setKnob({ x: dx, y: dy });

      const nx = dx / radius; // right positive
      const ny = -dy / radius; // up (forward) positive
      // Arcade mixing; normalize so neither track exceeds 1 while keeping ratio
      let left = ny + nx;
      let right = ny - nx;
      const m = Math.max(1, Math.abs(left), Math.abs(right));
      onChange(left / m, right / m);
    },
    [onChange]
  );

  const handleDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    active.current = true;
    onStart();
    compute(e.clientX, e.clientY);
  };

  const handleMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!active.current) return;
    compute(e.clientX, e.clientY);
  };

  const handleUp = () => {
    if (!active.current) return;
    active.current = false;
    setKnob({ x: 0, y: 0 });
    onEnd();
  };

  return (
    <div
      ref={baseRef}
      className={`joystick ${disabled ? "disabled" : ""}`}
      onPointerDown={handleDown}
      onPointerMove={handleMove}
      onPointerUp={handleUp}
      onPointerCancel={handleUp}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="joystick-ring" />
      <div
        className="joystick-knob"
        style={{ transform: `translate(${knob.x}px, ${knob.y}px)` }}
      />
    </div>
  );
}
