// ---------------------------------------------------------------------------
// TemperatureGauge -- Vertical thermometer with clamp controls
// ---------------------------------------------------------------------------
//
// Clamping is engine state, so the gauge reports it rather than remembering it.
// The Scheme keeps it in `*temperature-clamped?*` -- set during a snag response
// (`answers.ss`), cleared by `undo-snag-condition` (`trace.ss:195`) -- and the
// display reads it. Petacat's store carries the same flag, fed by
// `GET /runs/{id}/temperature` and by each WebSocket snapshot.
//
// Two things follow. A clamp the server refuses lights nothing, because nothing
// on the server changed. And a clamp in force stays visible -- with its Unclamp
// button -- across any remounting of the gauge, and whether this display asked
// for the clamp or the engine imposed one on itself.
// ---------------------------------------------------------------------------

import { useState, useCallback } from 'react';
import { clampTemperature, unclampTemperature, describeApiError } from '@/api/client';
import { useRunStore } from '@/store/runStore';

export function TemperatureGauge() {
  const temperature = useRunStore((s) => s.temperature);
  const clamped = useRunStore((s) => s.temperatureClamped);
  const runId = useRunStore((s) => s.runId);
  const refreshTemperature = useRunStore((s) => s.refreshTemperature);

  const [showClampDialog, setShowClampDialog] = useState(false);
  const [clampValue, setClampValue] = useState('50');
  const [clampCycles, setClampCycles] = useState('0');
  const [error, setError] = useState<string | null>(null);

  // Color: blue (0) -> yellow (50) -> red (100)
  const t = Math.max(0, Math.min(100, temperature)) / 100;
  const r = Math.round(t * 255);
  const g = Math.round((1 - Math.abs(t - 0.5) * 2) * 200);
  const b = Math.round((1 - t) * 255);
  const fillColor = `rgb(${r}, ${g}, ${b})`;

  const handleToggleClamp = useCallback(() => {
    setShowClampDialog((prev) => !prev);
    setError(null);
  }, []);

  const handleClamp = useCallback(async () => {
    if (!runId) return;
    try {
      await clampTemperature(
        runId,
        parseFloat(clampValue),
        parseInt(clampCycles, 10) || 0,
      );
    } catch (err) {
      // The dialog stays open carrying the reason: the request is the only place
      // the failure is visible, since the gauge itself shows the engine and the
      // engine is unclamped.
      setError(describeApiError(err, 'clamp the temperature'));
      return;
    }
    setError(null);
    await refreshTemperature();
    setShowClampDialog(false);
  }, [runId, clampValue, clampCycles, refreshTemperature]);

  const handleUnclamp = useCallback(async () => {
    if (!runId) return;
    try {
      await unclampTemperature(runId);
    } catch (err) {
      setError(describeApiError(err, 'release the temperature clamp'));
      return;
    }
    setError(null);
    await refreshTemperature();
    setShowClampDialog(false);
  }, [runId, refreshTemperature]);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        height: '100%',
        justifyContent: 'center',
        gap: 6,
        position: 'relative',
        cursor: 'pointer',
      }}
      onClick={handleToggleClamp}
    >
      {/* Scale labels */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          width: 50,
          marginBottom: 2,
        }}
      >
        <span className="text-xs" style={{ color: '#f44336' }}>100</span>
      </div>

      {/* Thermometer body */}
      <div
        style={{
          width: 30,
          flex: 1,
          maxHeight: 200,
          minHeight: 60,
          background: 'var(--bg-card)',
          borderRadius: 15,
          border: clamped ? '2px solid var(--warning)' : '1px solid var(--border)',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        {/* Gradient fill from bottom */}
        <div
          style={{
            position: 'absolute',
            bottom: 0,
            left: 0,
            right: 0,
            height: `${temperature}%`,
            background: `linear-gradient(to top, #2196f3, ${fillColor})`,
            borderRadius: '0 0 14px 14px',
            transition: 'height 0.3s ease',
          }}
        />

        {/* Scale lines */}
        {[25, 50, 75].map((mark) => (
          <div
            key={mark}
            style={{
              position: 'absolute',
              bottom: `${mark}%`,
              left: 0,
              right: 0,
              height: 1,
              background: 'var(--border)',
              opacity: 0.5,
            }}
          />
        ))}
      </div>

      {/* Numeric value */}
      <div
        className="mono"
        style={{ fontSize: 18, fontWeight: 700, color: fillColor }}
      >
        {temperature.toFixed(0)}
      </div>

      {/* Clamped indicator */}
      {clamped && (
        <div
          style={{
            fontSize: 10,
            color: 'var(--warning)',
            fontWeight: 600,
            textTransform: 'uppercase',
          }}
        >
          Clamped
        </div>
      )}

      {/* Bottom label */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          width: 50,
        }}
      >
        <span className="text-xs" style={{ color: '#2196f3' }}>0</span>
      </div>

      {/* Clamp dialog */}
      {showClampDialog && (
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: '110%',
            transform: 'translateY(-50%)',
            background: 'var(--bg-panel)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: 10,
            zIndex: 100,
            boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
            minWidth: 160,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="text-xs" style={{ fontWeight: 600, marginBottom: 6, color: 'var(--text-accent)' }}>
            Temperature Clamp
          </div>

          <div style={{ marginBottom: 6 }}>
            <label className="text-xs text-muted">Value (0-100)</label>
            <input
              type="number"
              min={0}
              max={100}
              value={clampValue}
              onChange={(e) => setClampValue(e.target.value)}
              style={{ width: '100%', marginTop: 2 }}
            />
          </div>

          <div style={{ marginBottom: 8 }}>
            <label className="text-xs text-muted">Cycles (0 = indefinite)</label>
            <input
              type="number"
              min={0}
              value={clampCycles}
              onChange={(e) => setClampCycles(e.target.value)}
              style={{ width: '100%', marginTop: 2 }}
            />
          </div>

          <div style={{ display: 'flex', gap: 4 }}>
            <button
              className="primary"
              onClick={handleClamp}
              disabled={!runId}
              style={{ flex: 1, fontSize: 11 }}
            >
              Clamp
            </button>
            {clamped && (
              <button
                onClick={handleUnclamp}
                disabled={!runId}
                style={{ flex: 1, fontSize: 11 }}
              >
                Unclamp
              </button>
            )}
          </div>

          {error !== null && (
            <div
              role="alert"
              className="text-xs"
              style={{ marginTop: 6, color: 'var(--error)' }}
            >
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
