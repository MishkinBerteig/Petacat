// ---------------------------------------------------------------------------
// TrainingPanel -- the Trainings view: the list on the left, the selected training on the right
// ---------------------------------------------------------------------------
//
// A Training runs many problems, each over many seeds, on every core, and keeps its
// results in the database (server/trainings). This view creates them, adds problems to
// them while they run, and reads the results back as distributions.
//
// Polling: the list every 3 s; the selected training and the problems page every 1.5 s
// while the training is running and every 5 s otherwise. All of it stops on unmount.
// ---------------------------------------------------------------------------

import { useEffect, useState } from 'react';
import { ApiError, describeApiError, getTraining, listTrainings } from '@/api/client';
import type { TrainingListResponse, TrainingSummary } from '@/types';
import { TrainingDetail } from './TrainingDetail';
import { TrainingList, describeExecutor } from './TrainingList';
import { NewTrainingForm } from './NewTrainingForm';
import { ControlHelp, errorStyle, noticeStyle, sectionLabelStyle, usePolling } from './shared';

const LIST_POLL_MS = 3000;
const RUNNING_POLL_MS = 1500;
const IDLE_POLL_MS = 5000;

export interface TrainingPanelProps {
  /** A training to select straight away, from `#/training/42`. */
  initialTrainingId?: number | null;
}

/** Unavailable (no database, feature off): the server's own explanation, plainly. */
function unavailableText(err: unknown): string | null {
  if (err instanceof ApiError && (err.status === 404 || err.status === 503)) {
    return err.detail || 'Trainings are not available on this server.';
  }
  return null;
}

export function TrainingPanel({ initialTrainingId = null }: TrainingPanelProps) {
  const [list, setList] = useState<TrainingListResponse | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(initialTrainingId);
  const [selected, setSelected] = useState<TrainingSummary | null>(null);
  const [selectedError, setSelectedError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  // `#/training/<id>` can change under us (a link followed while the view is open).
  useEffect(() => {
    if (initialTrainingId !== null) setSelectedId(initialTrainingId);
  }, [initialTrainingId]);

  const refreshList = async () => {
    try {
      const res = await listTrainings();
      setList(res);
      setListError(null);
      setUnavailable(null);
    } catch (err) {
      const text = unavailableText(err);
      if (text) {
        setUnavailable(text);
        setListError(null);
      } else {
        setListError(describeApiError(err, 'load the trainings'));
      }
    }
  };
  usePolling(refreshList, LIST_POLL_MS);

  const state = selected?.id === selectedId ? selected.state : null;
  usePolling(
    async () => {
      if (selectedId === null) return;
      try {
        const b = await getTraining(selectedId);
        setSelected(b);
        setSelectedError(null);
      } catch (err) {
        setSelectedError(describeApiError(err, 'load the training'));
      }
    },
    selectedId === null ? null : state === 'running' ? RUNNING_POLL_MS : IDLE_POLL_MS,
    selectedId,
  );

  const select = (id: number | null) => {
    setSelectedId(id);
    setSelected(null);
    setSelectedError(null);
    setNotice(null);
    setCreating(false);
    window.location.hash = id === null ? '/training' : `/training/${id}`;
  };

  const current = selected && selected.id === selectedId ? selected : null;
  const onTrainingChanged = (b: TrainingSummary) => {
    setSelected(b);
    void refreshList();
  };

  return (
    <div
      data-testid="trainings-panel"
      style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 280px) 1fr', gap: 10, height: '100%', minHeight: 0 }}
    >
      {/* ---- Left: the list ---- */}
      <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, borderRight: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '6px 8px', gap: 6 }}>
          <div style={sectionLabelStyle}>Trainings</div>
          <ControlHelp topic="training" label="Trainings" />
          <span style={{ flex: 1 }} />
          <button
            onClick={() => {
              setCreating(true);
              setNotice(null);
            }}
            disabled={unavailable !== null}
          >
            New training
          </button>
        </div>
        {list && (
          <div className="text-xs text-muted mono" style={{ padding: '0 8px 6px' }} data-testid="executor-line">
            {describeExecutor(list.executor)}
          </div>
        )}
        <div style={{ overflow: 'auto', flex: 1 }}>
          {unavailable && (
            <div role="status" style={{ ...noticeStyle, margin: 8 }} data-testid="trainings-unavailable">
              {unavailable}
            </div>
          )}
          {listError && (
            <div role="alert" style={{ ...errorStyle, margin: 8 }}>
              {listError}
            </div>
          )}
          {list && <TrainingList trainings={list.trainings} selectedId={selectedId} onSelect={select} />}
        </div>
      </div>

      {/* ---- Right: the form or the selected training ---- */}
      <div style={{ overflow: 'auto', padding: '6px 8px 6px 0', minHeight: 0 }}>
        {creating ? (
          <NewTrainingForm
            limits={list?.limits ?? null}
            defaults={list?.defaults ?? null}
            onCancel={() => setCreating(false)}
            onCreated={(training, warning) => {
              void refreshList();
              select(training.id);
              setSelected(training);
              setNotice(warning);
            }}
          />
        ) : selectedId === null ? (
          <div className="text-muted text-sm" style={{ padding: 12 }}>
            {unavailable
              ? 'Trainings are unavailable on this server.'
              : list && list.trainings.length === 0
                ? 'Create a training to begin.'
                : 'Select a training to see its problems.'}
          </div>
        ) : current ? (
          <>
            {selectedError && (
              <div role="alert" style={errorStyle}>
                {selectedError}
              </div>
            )}
            <TrainingDetail
              key={current.id}
              training={current}
              limits={list?.limits ?? null}
              notice={notice}
              onTrainingChanged={onTrainingChanged}
              onDeleted={() => {
                select(null);
                void refreshList();
              }}
            />
          </>
        ) : selectedError ? (
          <div role="alert" style={errorStyle}>
            {selectedError}
          </div>
        ) : (
          <div className="text-muted text-sm" style={{ padding: 12 }}>
            Loading training…
          </div>
        )}
      </div>
    </div>
  );
}
