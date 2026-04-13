"""RunService — orchestrates engine execution with DB persistence.

Creates runs, steps codelets, persists snapshots, manages lifecycle.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.memory import AnswerDescription, EpisodicMemory, SnagDescription
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineContext, EngineRunner, STATUS_ANSWER_FOUND, STATUS_HALTED, STATUS_PAUSED, STATUS_RUNNING, StepResult
from server.engine.trace import SNAG
from server.models.run import (
    AnswerDescriptionRow,
    CycleSnapshot,
    Run,
    SnagDescriptionRow,
    TraceEventRow,
)
from server.services.snapshot_service import (
    save_cycle_snapshot,
    serialize_themespace_state,
)


# Shared cross-run episodic memory (per-process)
_global_memory = EpisodicMemory()


@dataclass
class RunInfo:
    run_id: int
    status: str
    codelet_count: int
    temperature: float
    initial: str
    modified: str
    target: str
    answer: str | None


class RunService:
    """Orchestrates engine + DB persistence."""

    def __init__(self, meta: MetadataProvider) -> None:
        self.meta = meta
        self._runners: dict[int, EngineRunner] = {}
        # Per-runner control state
        self._breakpoints: dict[int, int | None] = {}
        self._step_sizes: dict[int, int] = {}
        self._stop_flags: dict[int, bool] = {}

    # ------------------------------------------------------------------
    # Existing methods
    # ------------------------------------------------------------------

    async def create_run(
        self,
        session: AsyncSession,
        initial: str,
        modified: str,
        target: str,
        answer: str | None = None,
        seed: int = 0,
    ) -> RunInfo:
        """Create a new run, initialize the engine, save initial snapshot."""
        run = Run(
            initial_string=initial,
            modified_string=modified,
            target_string=target,
            answer_string=answer,
            seed=seed,
            status="initialized",
            justify_mode=answer is not None,
        )
        session.add(run)
        await session.flush()

        runner = EngineRunner(self.meta)
        runner.init_mcat(initial, modified, target, answer=answer, seed=seed,
                         memory=_global_memory)
        self._runners[run.id] = runner

        await save_cycle_snapshot(session, run.id, runner.ctx)
        await session.commit()

        return RunInfo(
            run_id=run.id,
            status="initialized",
            codelet_count=0,
            temperature=runner.ctx.temperature.value,
            initial=initial,
            modified=modified,
            target=target,
            answer=answer,
        )

    async def step(
        self,
        session: AsyncSession,
        run_id: int,
        n: int = 1,
    ) -> list[StepResult]:
        """Step N codelets, persisting snapshots at cycle boundaries."""
        runner = self._runners.get(run_id)
        if runner is None:
            raise ValueError(f"Run {run_id} not found or not loaded")

        results = []
        ucl = self.meta.get_param("update_cycle_length", 15)

        for _ in range(n):
            trace_before = len(runner.ctx.trace.events)
            step_result = runner.step_mcat()
            results.append(step_result)

            # Persist new trace events to DB
            await self._persist_new_trace_events(
                session, run_id, runner.ctx, trace_before,
            )

            # Persist answer/snag if found
            if step_result.answer_found:
                await self._persist_answer(session, run_id, runner.ctx)

            # Save snapshot at cycle boundaries
            if runner.ctx.codelet_count % ucl == 0:
                await save_cycle_snapshot(session, run_id, runner.ctx)

            # Stop stepping if an answer was found
            if step_result.answer_found:
                break

        # Update run row — include answer_string if found
        update_values: dict = {
            "codelet_count": runner.ctx.codelet_count,
            "temperature": runner.ctx.temperature.value,
            "status": runner.status,
        }
        if runner.ctx.workspace.answer_string is not None:
            update_values["answer_string"] = runner.ctx.workspace.answer_string.text

        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(**update_values)
        )
        await session.commit()
        return results

    async def get_run_info(self, session: AsyncSession, run_id: int) -> RunInfo | None:
        """Get current run info."""
        result = await session.execute(select(Run).where(Run.id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            return None
        return RunInfo(
            run_id=run.id,
            status=run.status,
            codelet_count=run.codelet_count,
            temperature=run.temperature,
            initial=run.initial_string,
            modified=run.modified_string,
            target=run.target_string,
            answer=run.answer_string,
        )

    def get_runner(self, run_id: int) -> EngineRunner | None:
        return self._runners.get(run_id)

    def get_workspace_state(self, run_id: int) -> dict | None:
        """Get current workspace state as a dict."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None
        from server.services.snapshot_service import serialize_workspace_state
        return serialize_workspace_state(runner.ctx)

    def get_slipnet_state(self, run_id: int) -> dict | None:
        """Get current slipnet activations."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None
        return {
            name: {
                "activation": node.activation,
                "conceptual_depth": node.conceptual_depth,
                "frozen": node.frozen,
            }
            for name, node in runner.ctx.slipnet.nodes.items()
        }

    def get_coderack_state(self, run_id: int) -> dict | None:
        """Get current coderack contents."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None
        return {
            "total_count": runner.ctx.coderack.total_count,
            "type_counts": runner.ctx.coderack.get_codelet_type_counts(),
        }

    def get_temperature(self, run_id: int) -> float | None:
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None
        return runner.ctx.temperature.value

    # ------------------------------------------------------------------
    # New methods
    # ------------------------------------------------------------------

    async def list_runs(
        self, session: AsyncSession, limit: int = 50, offset: int = 0
    ) -> tuple[list[RunInfo], int]:
        """Query runs table, returning (runs, total_count)."""
        count_result = await session.execute(select(func.count()).select_from(Run))
        total = count_result.scalar() or 0

        result = await session.execute(
            select(Run).order_by(Run.id.desc()).limit(limit).offset(offset)
        )
        rows = result.scalars().all()
        runs = [
            RunInfo(
                run_id=r.id,
                status=r.status,
                codelet_count=r.codelet_count,
                temperature=r.temperature,
                initial=r.initial_string,
                modified=r.modified_string,
                target=r.target_string,
                answer=r.answer_string,
            )
            for r in rows
        ]
        return runs, total

    async def run_to_completion(
        self, session: AsyncSession, run_id: int, max_steps: int = 0
    ) -> RunInfo:
        """Step in a loop until answer found, max_steps reached, or stop flag set."""
        runner = self._runners.get(run_id)
        if runner is None:
            raise ValueError(f"Run {run_id} not found or not loaded")

        self._stop_flags[run_id] = False
        runner.status = STATUS_RUNNING

        # Update DB status to running
        await session.execute(
            update(Run).where(Run.id == run_id).values(status="running")
        )
        await session.commit()

        ucl = self.meta.get_param("update_cycle_length", 15)
        step = 0

        while runner.status == STATUS_RUNNING:
            if max_steps > 0 and step >= max_steps:
                runner.status = STATUS_HALTED
                break

            if self._stop_flags.get(run_id, False):
                runner.status = STATUS_PAUSED
                break

            # Check breakpoint
            bp = self._breakpoints.get(run_id)
            if bp is not None and runner.ctx.codelet_count >= bp:
                runner.status = STATUS_PAUSED
                break

            trace_before = len(runner.ctx.trace.events)
            step_result = runner.step_mcat()

            # Persist new trace events
            await self._persist_new_trace_events(
                session, run_id, runner.ctx, trace_before,
            )

            if step_result.answer_found:
                runner.status = STATUS_ANSWER_FOUND
                await self._persist_answer(session, run_id, runner.ctx)

            # Save snapshot at cycle boundaries
            if runner.ctx.codelet_count % ucl == 0:
                await save_cycle_snapshot(session, run_id, runner.ctx)

            step += 1

            # Yield event loop so concurrent requests (polling, stop) get served
            await asyncio.sleep(0)

        # Final update
        status_str = runner.status
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(
                codelet_count=runner.ctx.codelet_count,
                temperature=runner.ctx.temperature.value,
                status=status_str,
                answer_string=runner.ctx.workspace.answer_string.text
                if runner.ctx.workspace.answer_string
                else None,
            )
        )
        await session.commit()
        self._stop_flags.pop(run_id, None)

        return RunInfo(
            run_id=run_id,
            status=status_str,
            codelet_count=runner.ctx.codelet_count,
            temperature=runner.ctx.temperature.value,
            initial=runner.ctx.workspace.initial_string.text,
            modified=runner.ctx.workspace.modified_string.text,
            target=runner.ctx.workspace.target_string.text,
            answer=runner.ctx.workspace.answer_string.text
            if runner.ctx.workspace.answer_string
            else None,
        )

    def stop_run(self, run_id: int) -> None:
        """Set stop flag to interrupt a running run."""
        runner = self._runners.get(run_id)
        if runner is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        self._stop_flags[run_id] = True

    async def reset_run(self, session: AsyncSession, run_id: int) -> RunInfo:
        """Re-initialize the engine with the same parameters."""
        runner = self._runners.get(run_id)
        if runner is None:
            raise ValueError(f"Run {run_id} not found or not loaded")

        # Get original params from DB
        result = await session.execute(select(Run).where(Run.id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            raise ValueError(f"Run {run_id} not found in database")

        # Re-init engine
        runner.init_mcat(
            run.initial_string,
            run.modified_string,
            run.target_string,
            answer=run.answer_string,
            seed=run.seed,
            memory=_global_memory,
        )

        # Delete old snapshots and trace events
        await session.execute(
            delete(CycleSnapshot).where(CycleSnapshot.run_id == run_id)
        )
        await session.execute(
            delete(TraceEventRow).where(TraceEventRow.run_id == run_id)
        )

        # Reset DB row
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(
                status="initialized",
                codelet_count=0,
                temperature=runner.ctx.temperature.value,
            )
        )

        await save_cycle_snapshot(session, run_id, runner.ctx)
        await session.commit()

        # Clear control state
        self._breakpoints.pop(run_id, None)
        self._step_sizes.pop(run_id, None)
        self._stop_flags.pop(run_id, None)

        return RunInfo(
            run_id=run_id,
            status="initialized",
            codelet_count=0,
            temperature=runner.ctx.temperature.value,
            initial=run.initial_string,
            modified=run.modified_string,
            target=run.target_string,
            answer=run.answer_string,
        )

    async def delete_run(self, session: AsyncSession, run_id: int) -> None:
        """Delete a run and all associated state from DB and memory."""
        # Remove from in-memory runners
        self._runners.pop(run_id, None)
        self._breakpoints.pop(run_id, None)
        self._step_sizes.pop(run_id, None)
        self._stop_flags.pop(run_id, None)

        # Delete associated rows
        await session.execute(
            delete(CycleSnapshot).where(CycleSnapshot.run_id == run_id)
        )
        await session.execute(
            delete(TraceEventRow).where(TraceEventRow.run_id == run_id)
        )
        await session.execute(delete(Run).where(Run.id == run_id))
        await session.commit()

    async def delete_all_runs(self, session: AsyncSession) -> int:
        """Delete ALL runs, snapshots, trace events, and clear episodic memory."""
        # Clear in-memory state
        self._runners.clear()
        self._breakpoints.clear()
        self._step_sizes.clear()
        self._stop_flags.clear()

        # Delete all DB rows
        await session.execute(delete(CycleSnapshot))
        await session.execute(delete(TraceEventRow))
        await session.execute(delete(AnswerDescriptionRow))
        await session.execute(delete(SnagDescriptionRow))

        count_result = await session.execute(select(func.count()).select_from(Run))
        count = count_result.scalar() or 0

        await session.execute(delete(Run))
        await session.commit()

        # Clear in-memory episodic memory
        _global_memory.clear()

        return count

    # ------------------------------------------------------------------
    # Trace & memory persistence helpers
    # ------------------------------------------------------------------

    async def _persist_new_trace_events(
        self,
        session: AsyncSession,
        run_id: int,
        ctx: EngineContext,
        trace_start: int,
    ) -> None:
        """Persist any new trace events added since trace_start index."""
        new_events = ctx.trace.events[trace_start:]
        for event in new_events:
            row = TraceEventRow(
                run_id=run_id,
                event_number=event.event_number,
                event_type=event.event_type,
                codelet_count=event.codelet_count,
                temperature=event.temperature,
                description=event.description,
                structures=None,  # Structures are complex objects; not serialized here
                theme_pattern=event.theme_pattern,
            )
            session.add(row)

            # If this is a snag event, also persist a SnagDescriptionRow
            if event.event_type == SNAG:
                snag_row = SnagDescriptionRow(
                    run_id=run_id,
                    problem=[
                        ctx.workspace.initial_string.text,
                        ctx.workspace.modified_string.text,
                        ctx.workspace.target_string.text,
                    ],
                    codelet_count=event.codelet_count,
                    temperature=event.temperature,
                    theme_pattern=event.theme_pattern,
                    description=event.description,
                )
                session.add(snag_row)

    async def _persist_answer(
        self,
        session: AsyncSession,
        run_id: int,
        ctx: EngineContext,
    ) -> None:
        """Persist the most recent answer from episodic memory to DB."""
        if not ctx.memory.answers:
            return
        latest = ctx.memory.answers[-1]
        latest.run_id = run_id
        row = AnswerDescriptionRow(
            run_id=run_id,
            problem=list(latest.problem),
            top_rule_description=latest.top_rule_description,
            bottom_rule_description=latest.bottom_rule_description,
            top_rule_quality=latest.top_rule_quality,
            bottom_rule_quality=latest.bottom_rule_quality,
            quality=latest.quality,
            temperature=latest.temperature,
            themes=latest.themes,
            unjustified_slippages=latest.unjustified_slippages,
        )
        session.add(row)

    # ------------------------------------------------------------------
    # DB-backed trace & memory reads
    # ------------------------------------------------------------------

    async def get_trace_events_from_db(
        self,
        session: AsyncSession,
        run_id: int,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Read trace events from the database."""
        query = select(TraceEventRow).where(TraceEventRow.run_id == run_id)
        if event_type is not None:
            query = query.where(TraceEventRow.event_type == event_type)
        query = query.order_by(TraceEventRow.event_number).offset(offset).limit(limit)
        result = await session.execute(query)
        return [
            {
                "event_number": r.event_number,
                "event_type": r.event_type,
                "codelet_count": r.codelet_count,
                "temperature": r.temperature,
                "description": r.description or "",
                "theme_pattern": r.theme_pattern,
            }
            for r in result.scalars().all()
        ]

    async def get_memory_state_from_db(self, session: AsyncSession) -> dict:
        """Read episodic memory from the database."""
        answers_result = await session.execute(
            select(AnswerDescriptionRow).order_by(AnswerDescriptionRow.id)
        )
        snags_result = await session.execute(
            select(SnagDescriptionRow).order_by(SnagDescriptionRow.id)
        )
        return {
            "answers": [
                {
                    "answer_id": a.id,
                    "run_id": a.run_id,
                    "problem": a.problem,
                    "top_rule_description": a.top_rule_description or "",
                    "bottom_rule_description": a.bottom_rule_description or "",
                    "top_rule_quality": a.top_rule_quality,
                    "bottom_rule_quality": a.bottom_rule_quality,
                    "quality": a.quality,
                    "temperature": a.temperature,
                    "themes": a.themes,
                    "unjustified_slippages": a.unjustified_slippages,
                }
                for a in answers_result.scalars().all()
            ],
            "snags": [
                {
                    "snag_id": s.id,
                    "run_id": s.run_id,
                    "problem": s.problem,
                    "codelet_count": s.codelet_count,
                    "temperature": s.temperature,
                    "theme_pattern": s.theme_pattern,
                    "description": s.description or "",
                }
                for s in snags_result.scalars().all()
            ],
        }

    async def rehydrate_memory(self, session: AsyncSession) -> None:
        """Load episodic memory from DB into the in-memory singleton."""
        answers_result = await session.execute(
            select(AnswerDescriptionRow).order_by(AnswerDescriptionRow.id)
        )
        for a in answers_result.scalars().all():
            desc = AnswerDescription(
                problem=tuple(a.problem),
                top_rule_description=a.top_rule_description or "",
                bottom_rule_description=a.bottom_rule_description or "",
                top_rule_quality=a.top_rule_quality or 0.0,
                bottom_rule_quality=a.bottom_rule_quality or 0.0,
                quality=a.quality or 0.0,
                temperature=a.temperature or 0.0,
                themes=a.themes or {},
                unjustified_slippages=a.unjustified_slippages or [],
                run_id=a.run_id,
            )
            _global_memory.answers.append(desc)

        snags_result = await session.execute(
            select(SnagDescriptionRow).order_by(SnagDescriptionRow.id)
        )
        for s in snags_result.scalars().all():
            desc = SnagDescription(
                problem=tuple(s.problem),
                codelet_count=s.codelet_count or 0,
                temperature=s.temperature or 0.0,
                theme_pattern=s.theme_pattern or {},
                description=s.description or "",
                run_id=s.run_id,
            )
            _global_memory.snags.append(desc)

    def get_themespace_state(self, run_id: int) -> dict | None:
        """Serialize the current themespace state for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None
        return serialize_themespace_state(runner.ctx)

    def get_trace_events(
        self,
        run_id: int,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict] | None:
        """Return trace events from the in-memory trace, with optional filtering."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None

        events = runner.ctx.trace.events

        # Filter by event_type if specified
        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]

        # Apply offset and limit
        events = events[offset : offset + limit]

        return [
            {
                "event_number": e.event_number,
                "event_type": e.event_type,
                "codelet_count": e.codelet_count,
                "temperature": e.temperature,
                "description": e.description,
                "theme_pattern": e.theme_pattern,
            }
            for e in events
        ]

    def get_memory_state(self) -> dict:
        """Return episodic memory contents (cross-run)."""
        return {
            "answers": [
                {
                    "answer_id": a.answer_id,
                    "run_id": a.run_id,
                    "problem": list(a.problem),
                    "top_rule_description": a.top_rule_description,
                    "bottom_rule_description": a.bottom_rule_description,
                    "top_rule_quality": a.top_rule_quality,
                    "bottom_rule_quality": a.bottom_rule_quality,
                    "quality": a.quality,
                    "temperature": a.temperature,
                    "themes": a.themes,
                    "unjustified_slippages": a.unjustified_slippages,
                }
                for a in _global_memory.answers
            ],
            "snags": [
                {
                    "snag_id": s.snag_id,
                    "run_id": s.run_id,
                    "problem": list(s.problem),
                    "codelet_count": s.codelet_count,
                    "temperature": s.temperature,
                    "theme_pattern": s.theme_pattern,
                    "description": s.description,
                }
                for s in _global_memory.snags
            ],
        }

    def get_commentary(self, run_id: int, eliza_mode: bool = False) -> dict | None:
        """Return accumulated commentary text for the given run.

        Reads from the CommentaryLog on the EngineContext and renders
        all paragraphs in the requested voice mode.  Toggling eliza_mode
        re-renders the same paragraphs in the alternate voice — no
        regeneration needed, matching original Scheme behavior.
        """
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None

        return {
            "run_id": run_id,
            "commentary": runner.ctx.commentary.render(eliza_mode),
            "eliza_mode": eliza_mode,
            "paragraph_count": runner.ctx.commentary.count,
        }

    # ------------------------------------------------------------------
    # Breakpoint & execution control
    # ------------------------------------------------------------------

    def set_breakpoint(self, run_id: int, codelet_count: int) -> dict:
        """Set a breakpoint at a given codelet count."""
        if run_id not in self._runners:
            raise ValueError(f"Run {run_id} not found or not loaded")
        self._breakpoints[run_id] = codelet_count
        return {"run_id": run_id, "breakpoint": codelet_count}

    def clear_breakpoint(self, run_id: int) -> dict:
        """Clear the breakpoint for a run."""
        if run_id not in self._runners:
            raise ValueError(f"Run {run_id} not found or not loaded")
        self._breakpoints.pop(run_id, None)
        return {"run_id": run_id, "breakpoint": None}

    def set_step_size(self, run_id: int, step_size: int) -> dict:
        """Set the step size for the given run."""
        if run_id not in self._runners:
            raise ValueError(f"Run {run_id} not found or not loaded")
        self._step_sizes[run_id] = step_size
        return {"run_id": run_id, "step_size": step_size}

    # ------------------------------------------------------------------
    # Temperature clamping
    # ------------------------------------------------------------------

    def clamp_temperature(self, run_id: int, value: float, cycles: int = 0) -> dict:
        """Clamp the temperature for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        runner.ctx.temperature.clamp(value, cycles)
        return {
            "run_id": run_id,
            "temperature": runner.ctx.temperature.value,
            "clamped": True,
            "clamp_value": value,
            "clamp_cycles": cycles,
        }

    def unclamp_temperature(self, run_id: int) -> dict:
        """Unclamp the temperature for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        runner.ctx.temperature.unclamp()
        return {
            "run_id": run_id,
            "temperature": runner.ctx.temperature.value,
            "clamped": False,
        }

    # ------------------------------------------------------------------
    # Slipnet node clamping
    # ------------------------------------------------------------------

    def clamp_node(self, run_id: int, node_name: str, cycles: int = 0) -> dict:
        """Clamp a slipnet node for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        node = runner.ctx.slipnet.nodes.get(node_name)
        if node is None:
            raise ValueError(f"Slipnet node '{node_name}' not found")
        node.clamp(cycles)
        return {
            "run_id": run_id,
            "node_name": node_name,
            "clamped": True,
            "activation": node.activation,
            "clamp_cycles": cycles,
        }

    def unclamp_node(self, run_id: int, node_name: str) -> dict:
        """Unclamp a slipnet node for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        node = runner.ctx.slipnet.nodes.get(node_name)
        if node is None:
            raise ValueError(f"Slipnet node '{node_name}' not found")
        node.unclamp()
        return {
            "run_id": run_id,
            "node_name": node_name,
            "clamped": False,
            "activation": node.activation,
        }

    # ------------------------------------------------------------------
    # Theme clamping
    # ------------------------------------------------------------------

    def clamp_themes(self, run_id: int, themes: list[dict]) -> dict:
        """Clamp themes in the themespace for the given run.

        Each theme dict: {type, dimension, relation, activation}.
        """
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")

        clamped = []
        for t in themes:
            for cluster in runner.ctx.themespace.clusters:
                if (
                    cluster.theme_type == t.get("type", "")
                    and cluster.dimension == t.get("dimension", "")
                ):
                    theme = cluster.get_theme(t.get("relation"))
                    if theme is not None:
                        activation = t.get("activation", 100.0)
                        theme.clamp(activation)
                        clamped.append({
                            "type": cluster.theme_type,
                            "dimension": cluster.dimension,
                            "relation": theme.relation,
                            "activation": theme.activation,
                        })
        return {"run_id": run_id, "clamped_themes": clamped}

    def unclamp_themes(self, run_id: int) -> dict:
        """Unclamp all themes in the themespace for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")

        for cluster in runner.ctx.themespace.clusters:
            for theme in cluster.themes:
                theme.unclamp()
        return {"run_id": run_id, "unclamped": True}

    # ------------------------------------------------------------------
    # Codelet clamping
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Spreading activation threshold
    # ------------------------------------------------------------------

    def set_spreading_threshold(self, run_id: int, threshold: int) -> dict:
        """Set the spreading activation threshold for the given run.

        0 = all active nodes spread (permissive).
        100 = only fully-active nodes spread (original Scheme behaviour).
        """
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        threshold = max(0, min(100, threshold))
        runner.ctx.spreading_activation_threshold = threshold
        return {
            "run_id": run_id,
            "spreading_activation_threshold": threshold,
        }

    def get_spreading_threshold(self, run_id: int) -> dict:
        """Get the current spreading activation threshold for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        return {
            "run_id": run_id,
            "spreading_activation_threshold": runner.ctx.spreading_activation_threshold,
        }

    # ------------------------------------------------------------------
    # Codelet clamping
    # ------------------------------------------------------------------

    def clamp_codelets(self, run_id: int, codelet_type: str, urgency: int) -> dict:
        """Clamp a codelet type to a minimum urgency for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        runner.ctx.coderack.clamp_codelet_type(codelet_type, urgency)
        return {
            "run_id": run_id,
            "codelet_type": codelet_type,
            "urgency": urgency,
            "clamped": True,
        }

    def unclamp_codelets(self, run_id: int, codelet_type: str) -> dict:
        """Unclamp a codelet type for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        runner.ctx.coderack.unclamp_codelet_type(codelet_type)
        return {
            "run_id": run_id,
            "codelet_type": codelet_type,
            "clamped": False,
        }
