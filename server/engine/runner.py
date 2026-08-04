"""Engine Runner — main control loop.

Orchestrates init_mcat, step_mcat, run_mcat, update_everything.

Scheme source: run.ss
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("petacat.engine")

from server.engine.codelet_dsl.builtins import get_builtins
from server.engine.commentary import CommentaryLog, CommentaryWriter, emit_new_problem
from server.engine.codelet_dsl.interpreter import CodeletInterpreter, CodeletRegistry
from server.engine.access import AccessRecorder
from server.engine.coderack import Codelet, Coderack
from server.engine.ids import IdAllocator, use_allocator
from server.engine.memory import EpisodicMemory
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.engine.sink import STRUCTURE_BUILT, NullSink, RunSink
from server.engine.slipnet import Slipnet
from server.engine.staleness import StaleView
from server.engine.temperature import Temperature
from server.engine.themes import Themespace
from server.engine.trace import (
    CONCEPT_ACTIVATION,
    TemporalTrace,
    TraceEvent,
    concept_activation_importance,
)
from server.engine.workspace import Workspace
from server.engine.workspace_structures import WorkspaceStructure

# Run status string constants (values live in DB run_statuses table)
STATUS_INITIALIZED = "initialized"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_ANSWER_FOUND = "answer_found"
STATUS_HALTED = "halted"
STATUS_GAVE_UP = "gave_up"


@dataclass
class StepResult:
    """Result of executing one codelet."""

    codelet_type: str = ""
    codelet_count: int = 0
    event: TraceEvent | None = None
    answer_found: bool = False
    answer: str | None = None
    #: A jootser concluded the program is looping with no alternatives left
    #: (§4.5.2).  Giving up is a real outcome, distinct from running out of
    #: codelets, so callers need to be able to tell the two apart.
    gave_up: bool = False
    #: Did the state this codelet read still hold when it committed (WP4.2)?  Always
    #: True serially, and only meaningful when access tracking is on.  Under
    #: free-running, False is the conflict that becomes a fizzle.
    premises_held: bool = True


@dataclass
class RunResult:
    """Result of a complete run."""

    status: str = STATUS_HALTED
    answers: list[str] = field(default_factory=list)
    codelet_count: int = 0
    steps: list[StepResult] = field(default_factory=list)


class EngineContext:
    """Bundles all engine state for codelet execution."""

    def __init__(
        self,
        workspace: Workspace,
        slipnet: Slipnet,
        coderack: Coderack,
        themespace: Themespace,
        trace: TemporalTrace,
        memory: EpisodicMemory,
        temperature: Temperature,
        commentary: CommentaryWriter,
        rng: RNG,
        meta: MetadataProvider,
        ids: IdAllocator | None = None,
        sink: RunSink | None = None,
    ) -> None:
        #: This run's identifier counters.  Held here rather than on the classes that
        #: allocate from it so that a run's identifiers depend on the run and not on
        #: what the process happened to execute before it (``server/engine/ids.py``).
        self.ids = ids if ids is not None else IdAllocator()
        self.workspace = workspace
        self.slipnet = slipnet
        self.coderack = coderack
        self.themespace = themespace
        self.trace = trace
        self.memory = memory
        self.temperature = temperature
        self.commentary = commentary
        self.rng = rng
        self.meta = meta
        #: Where this run's record goes.  ``NullSink`` rather than ``None`` so every
        #: emission site can call unconditionally; the engine never learns which mode
        #: is attached (``server/engine/sink.py``).
        self.sink: RunSink = sink if sink is not None else NullSink()
        self.codelet_count: int = 0
        #: Has this run's terminal outcome already been claimed?  Free-running lets a
        #: codelet finish after another has ended the run, and ``report_answer`` would
        #: otherwise write a second ``AnswerDescription`` into a memory that outlives
        #: the Run.  Cleared whenever the run starts or resumes, so a resumed run can
        #: still go on to find a genuinely *different* answer, as MetaCat does.
        self.run_ended: bool = False
        self.justify_mode: bool = False
        self.self_watching_enabled: bool = True
        self.spreading_activation_threshold: int = 100

        #: The Workspace objects the most recent rule application failed on — the
        #: Scheme's ``<failure-result>`` objects (``answers.ss:1145-1150``), which is
        #: where ``make-snag-event`` (``trace.ss:1055-1059``) gets a snag's objects.
        #: Written by the ``apply_rule`` builtin, read by the ``record_snag`` that
        #: follows it within the same codelet; not run state, so nothing restores it.
        self.last_failure_objects: list = []

        #: Which of the Scheme's three ``<failure-result>`` shapes the last rule
        #: application produced — ``"swap"``, ``"conflict"`` or ``"change"``
        #: (``answers.ss:1145-1150``).  ``make-snag-event`` records it as the snag
        #: type, which is what the snag's own explanation and the memory's
        #: snag-equality test are written against.  Petacat hard-coded ``"change"``.
        self.last_failure_kind: str = "change"

        #: The snag response's restart (``answers.ss:1189-1191``): empty the Coderack,
        #: post the initial codelets afresh, run one full update.  A callable rather
        #: than an import because it is the *runner's* loop the snag reaches into, and
        #: ``server/engine/`` may not import upwards.  Set by ``EngineRunner`` at
        #: ``init_mcat``; ``None`` only in tests that build a context by hand.
        self.on_snag_restart: Any = None

        #: ``report-new-answer``'s first act is ``(update-everything)``
        #: (``answers.ss:24``), so the temperature and structure strengths an answer
        #: is recorded with are this instant's rather than up to fifteen codelets
        #: stale.  Same shape and same reason as ``on_snag_restart``: the update
        #: cycle belongs to the runner's loop, and ``server/engine/`` may not import
        #: upwards.  ``None`` only in tests that build a context by hand.
        self.on_update_everything: Any = None

        #: How many codelets behind the live Workspace each codelet reads (WP0.5).
        #: 0 — the default — is ordinary live execution; nothing in
        #: ``server/engine/staleness.py`` runs.  See that module for what a
        #: non-zero value delays and what it deliberately does not.
        self.staleness_delay: int = 0
        self.view_history: deque[StaleView] = deque(maxlen=1)

        #: Read/write-set tracking (WP4.2).  Absent rather than idle when off, so
        #: serial execution — the permanent reference mode — pays one boolean check
        #: rather than the recorder's cost.
        self.track_access: bool = False
        self.access: AccessRecorder | None = None

        #: Held while a codelet mutates the Workspace, under free-running (WP4.4).
        #: ``None`` when serial, so the serial loop takes no lock at all rather than an
        #: uncontended one — the reference mode must not pay for machinery it cannot use.
        #: A codelet is a long read-and-decide followed by a short mutation, so
        #: serialising only the mutation leaves the expensive part parallel.
        self.commit_lock: Any = None

    def enable_access_tracking(self, enabled: bool = True) -> None:
        """Turn read/write-set recording on or off.

        Serially the recorder only observes; its validation always passes, because
        nothing runs between a codelet's reads and its commit.  That is what makes
        turning it on a no-op for behaviour and a source of telemetry for WP4.4.
        """
        self.track_access = bool(enabled)
        if enabled and self.access is None:
            self.access = AccessRecorder()
        elif not enabled:
            self.access = None

    def set_staleness_delay(self, delay: int) -> None:
        """Set the read lag, in codelets, and resize the history that serves it.

        The history holds exactly ``delay`` views.  A view is captured at the top of
        each step, *before* ``codelet_count`` is incremented, so the view taken at
        the start of codelet *k* is labelled *k-1*; keeping ``delay`` of them leaves
        the oldest at *k - delay* while codelet *k* runs, which is the lag asked for.
        """
        self.staleness_delay = max(0, int(delay))
        self.view_history = deque(
            self.view_history, maxlen=max(1, self.staleness_delay)
        )

    def capture_view(self) -> None:
        """Record the current Workspace for codelets to read ``delay`` codelets hence."""
        if self.staleness_delay:
            self.view_history.append(StaleView(self))


class EngineRunner:
    """The main engine runner."""

    def __init__(self, meta: MetadataProvider) -> None:
        self.meta = meta
        self.ctx: EngineContext | None = None
        self.status: str = STATUS_INITIALIZED
        self._answers: list[str] = []
        #: Guards ``on_turn_end`` against being emitted more than once per Run.
        self._turn_ended: bool = False
        #: How many Trace events have been handed to the sink so far.
        self._trace_emitted: int = 0

        # Build the codelet interpreter and registry
        self._interpreter = CodeletInterpreter(builtins=get_builtins())
        self._registry = CodeletRegistry.from_metadata(meta, self._interpreter)

    # -- Identifier scoping ------------------------------------------------
    #
    # Codelets, workspace objects, workspace structures and trace events take their
    # identifiers from the run's ``IdAllocator``.  They reach it through the binding
    # in ``server/engine/ids.py`` rather than through their constructors, because the
    # DSL bodies in ``seed_data/codelet_types.json`` construct structures directly and
    # threading an allocator argument through them would make adding a codelet type a
    # code change again.
    #
    # The binding is re-established at each entry point rather than once per run.
    # That is not belt-and-braces: the service layer runs one API request per step,
    # each in its own asyncio task with its own context, so an allocator bound during
    # ``init_mcat`` would not be visible to the request that steps the run next.

    def init_mcat(
        self,
        initial: str,
        modified: str,
        target: str,
        answer: str | None = None,
        seed: int = 0,
        memory: EpisodicMemory | None = None,
        commentary: CommentaryWriter | None = None,
        sink: RunSink | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Initialize Metacat for a new run.

        Scheme: run.ss init-mcat.
        """
        with use_allocator(IdAllocator()) as ids:
            # Parameter overrides apply for this Run only, so the metadata is
            # replaced on the runner rather than mutated: two Runs in one process must
            # be able to disagree about the update cycle without disturbing each other.
            if parameters:
                self.meta = self.meta.with_overrides(parameters)
            self._init_mcat(
                initial, modified, target, answer, seed, memory, ids, commentary, sink,
            )

    def _init_mcat(
        self,
        initial: str,
        modified: str,
        target: str,
        answer: str | None,
        seed: int,
        memory: EpisodicMemory | None,
        ids: IdAllocator,
        commentary: CommentaryWriter | None = None,
        sink: RunSink | None = None,
    ) -> None:
        rng = RNG(seed)

        # Structures consult the Themespace for thematic compatibility; the
        # Scheme uses a global *themespace*, so bind ours before building any.
        WorkspaceStructure.set_themespace(None)

        # Build slipnet from metadata
        slipnet = Slipnet.from_metadata(self.meta)

        # Create workspace
        workspace = Workspace(initial, modified, target, answer, slipnet)
        # ``get-local-density`` walks *stochastically* chosen positional neighbours
        # (bonds.ss:136-160), so external strength draws on the RNG from call sites
        # that carry no RNG of their own — ``update-strength`` reaches the Scheme's
        # as a global.  Hang it off the Workspace, which is per *run*: a class-level
        # binding would let two runners in one process draw from each other.  Not
        # captured (``state_graph._ENVIRONMENT_FIELDS``) and not part of the
        # Workspace's restored state, so a restored run keeps its own.
        workspace.rng = rng

        # Create coderack.  It needs the RNG so it can enforce its own capacity
        # cap when codelets are posted.
        coderack = Coderack(self.meta)
        coderack.rng = rng

        # Create themespace, and bind it for structure thematic-compatibility
        themespace = Themespace(self.meta)
        WorkspaceStructure.set_themespace(themespace)

        # Create trace
        trace = TemporalTrace()

        # Use provided or new memory
        if memory is None:
            memory = EpisodicMemory()

        # Create temperature
        temperature = Temperature(
            initial=float(self.meta.get_param("initial_temperature", 100))
        )

        # Commentary is injected rather than constructed, so a mode that keeps no
        # record can supply a writer that discards (WP3.10).  The default preserves
        # the accumulating log, so nothing changes for a caller that does not care.
        if commentary is None:
            commentary = CommentaryLog()

        # Bundle context
        self.ctx = EngineContext(
            workspace=workspace,
            slipnet=slipnet,
            coderack=coderack,
            themespace=themespace,
            trace=trace,
            memory=memory,
            temperature=temperature,
            commentary=commentary,
            rng=rng,
            meta=self.meta,
            ids=ids,
            sink=sink,
        )

        # Set modes
        self.ctx.justify_mode = answer is not None
        self.ctx.self_watching_enabled = self.meta.get_param(
            "self_watching_enabled_default", True
        )
        self.ctx.spreading_activation_threshold = self.meta.get_param(
            "spreading_activation_threshold", 100
        )
        themespace.set_justify_mode(self.ctx.justify_mode)

        # Emit opening commentary (Scheme: run.ss:257-258)
        emit_new_problem(
            commentary, initial, modified, target, answer, self.ctx.justify_mode,
        )

        # Add initial descriptions to all letters (matches Scheme init-mcat)
        self._add_initial_descriptions(workspace, slipnet)

        # ``update-workspace-values`` (``run.ss:233``), before the first codelet.
        # Without it every object entered the run with its constructor defaults —
        # importance 0, every unhappiness and salience pinned at 100 — and the
        # description strengths were never computed at all, so the first update
        # cycle was the first time anything in the workspace had a real value.
        #
        # Note what this does *not* do: it runs before ``clamp_initially_relevant``,
        # exactly as the reference orders it, so the description *types* are still
        # inactive and no description is yet relevant.  Every raw importance is
        # therefore 0 and every relative importance falls back to the uniform
        # 100/n (``workspace-strings.ss:325-328``).  The leftmost and rightmost
        # letters get no head start here — they get it one cycle later, once the
        # clamp has made string-position-category active.
        self._update_workspace_values(workspace)

        # Clamp initially relevant slipnet nodes
        slipnet.clamp_initially_relevant(self.meta)

        # The snag response reaches back into the runner's loop; see
        # ``EngineContext.on_snag_restart``.
        self.ctx.on_snag_restart = self._restart_after_snag
        self.ctx.on_update_everything = self.update_everything

        # Post initial codelets
        self._post_initial_codelets()

        self.status = STATUS_INITIALIZED
        self._answers = []
        self._turn_ended = False
        self._trace_emitted = 0

        # Normal mode's first complete-state capture.  Emitted last, so the state the
        # sink sees is the one the first codelet will actually run against: initial
        # descriptions attached, slipnodes clamped, opening codelets posted.
        self.ctx.sink.on_run_created(self.ctx)

    def _add_initial_descriptions(self, workspace: Workspace, slipnet: Slipnet) -> None:
        """Add initial descriptions to all letters.

        Scheme: run.ss init-mcat — adds letter-category, string-position,
        and object-category descriptions, then sets their descriptors to
        full activation.
        """
        from server.engine.descriptions import Description
        from server.engine.workspace_objects import Letter

        letter_cat_node = slipnet.nodes.get("plato-letter-category")
        obj_cat_node = slipnet.nodes.get("plato-object-category")
        letter_obj_node = slipnet.nodes.get("plato-letter")
        str_pos_node = slipnet.nodes.get("plato-string-position-category")
        leftmost_node = slipnet.nodes.get("plato-leftmost")
        rightmost_node = slipnet.nodes.get("plato-rightmost")
        middle_node = slipnet.nodes.get("plato-middle")
        single_node = slipnet.nodes.get("plato-single")

        max_act = self.meta.get_param("max_activation", 100)

        # ``run.ss:221-226``: a problem containing any single-letter string starts
        # with the *concept* of object-category fully active.  A one-letter string
        # can only be mapped onto a multi-letter one by treating a letter and a
        # group as playing the same role, so the reference puts that idea on the
        # table before the first codelet runs rather than waiting for the run to
        # stumble into it.  Depth 90, so it stays above threshold for about seven
        # update cycles.
        if obj_cat_node and any(s.length == 1 for s in workspace.all_strings):
            obj_cat_node.activation = max_act

        for ws_string in workspace.all_strings:
            letters = [o for o in ws_string.objects if isinstance(o, Letter)]
            for letter in letters:
                # Letter-category description (e.g., letter-category: a)
                if letter_cat_node and letter.letter_category:
                    desc = Description(letter, letter_cat_node, letter.letter_category)
                    desc.proposal_level = desc.BUILT
                    letter.descriptions.append(desc)
                    # Activate the descriptor
                    letter.letter_category.activation = max_act

                # Object-category: letter
                if obj_cat_node and letter_obj_node:
                    desc = Description(letter, obj_cat_node, letter_obj_node)
                    desc.proposal_level = desc.BUILT
                    letter.descriptions.append(desc)
                    # ``run.ss:227-232`` activates *every* descriptor of every
                    # initial description, which includes ``plato-letter`` — the
                    # descriptor of the object-category description.  Leaving it
                    # at 0 skipped the brief early presence of the concept of a
                    # letter, which is what letter⇔group concept-mappings are
                    # weighed against.
                    letter_obj_node.activation = max_act

                # String-position descriptions
                if str_pos_node and len(letters) == 1:
                    # Single-letter string
                    if single_node:
                        desc = Description(letter, str_pos_node, single_node)
                        desc.proposal_level = desc.BUILT
                        letter.descriptions.append(desc)
                        single_node.activation = max_act
                elif str_pos_node:
                    if letter.left_string_pos == 0 and leftmost_node:
                        desc = Description(letter, str_pos_node, leftmost_node)
                        desc.proposal_level = desc.BUILT
                        letter.descriptions.append(desc)
                        leftmost_node.activation = max_act
                    if letter.right_string_pos == len(letters) - 1 and rightmost_node:
                        desc = Description(letter, str_pos_node, rightmost_node)
                        desc.proposal_level = desc.BUILT
                        letter.descriptions.append(desc)
                        rightmost_node.activation = max_act
                    if len(letters) % 2 == 1 and letter.left_string_pos == len(letters) // 2 and middle_node:
                        desc = Description(letter, str_pos_node, middle_node)
                        desc.proposal_level = desc.BUILT
                        letter.descriptions.append(desc)
                        middle_node.activation = max_act

    @staticmethod
    def _update_workspace_values(workspace: Workspace) -> None:
        """Scheme: ``update-workspace-values`` (``run.ss:325-344``).

        Structure strengths, then every object's importance / unhappiness /
        salience, then the workspace-level averages the mapping strengths are read
        off.  Called from two places, exactly as the reference calls it: once at
        the end of ``init-mcat`` and once at the top of ``update-everything``.
        """
        workspace.update_all_structure_strengths()
        workspace.update_all_object_values()
        workspace.update_average_unhappiness_values()

    def _post_initial_codelets(self) -> None:
        """Post the opening population of scouts.

        Scheme: ``post-initial-codelets`` (run.ss:275-283)::

            (repeat* (* 2 (length (tell *workspace* 'get-objects))) times
              (add-deferred-codelet bottom-up-bond-scout)
              (add-deferred-codelet bottom-up-bridge-scout))
            (post-deferred-codelets)

        ``2N`` iterations of *two* posts each — **4N** codelets, 36 for
        ``abc/abd/xyz``.  Petacat ran ``N`` iterations, so the run started with
        half the reference's scouts and reached its first update cycle with
        proportionally less built.

        Stamped with the codelet count that posts them, as ``add-codelet`` stamps
        every codelet (``coderack.ss:300-306``); posted as a deferred batch, so
        the members never evict one another.
        """
        ctx = self.ctx
        if ctx is None:
            return

        num_objects = len(ctx.workspace.all_objects)
        urgency = self.meta.get_urgency("very_low")

        batch: list[Codelet] = []
        for _ in range(2 * num_objects):
            batch.append(
                Codelet("bottom-up-bond-scout", urgency, time_stamp=ctx.codelet_count)
            )
            batch.append(
                Codelet("bottom-up-bridge-scout", urgency, time_stamp=ctx.codelet_count)
            )
        ctx.coderack.post_deferred(batch, ctx.codelet_count, ctx.rng)

    def _restart_after_snag(self) -> None:
        """The last three steps of ``process-snag`` (``answers.ss:1189-1191``).

        ``(tell *coderack* 'delete-all-codelets)``, ``(post-initial-codelets)``,
        ``(update-everything)`` — the "empty the Coderack and post the initial
        codelets afresh" reset the architecture's escape behaviour is built on.  None
        of it existed: the pre-snag population, including the evaluators and builders
        of the interpretation that just failed, carried straight on.

        The Scheme's explicit purge of proposed bonds, groups and bridges
        (``answers.ss:1176-1182``) needs no counterpart here, and its own comment says
        why: "Deleting all codelets automatically erases all proposed bonds, groups,
        and bridges".  In Petacat a proposed structure exists *only* as a codelet
        argument — there is no proposed registry to purge — so flushing the rack is
        the whole of it.
        """
        ctx = self.ctx
        if ctx is None:
            return
        ctx.coderack.clear()
        self._post_initial_codelets()
        self._update_everything(ctx)

    def step_mcat(self) -> StepResult:
        """Execute one codelet.

        Scheme: run.ss step-mcat.
        """
        ctx = self.ctx
        if ctx is None:
            return StepResult()
        with use_allocator(ctx.ids):
            return self._step_mcat(ctx)

    def _step_mcat(self, ctx: EngineContext) -> StepResult:
        result = StepResult()

        # Record the Workspace before this codelet touches it, so that with a
        # staleness delay configured the codelet reads the state of ``delay``
        # codelets ago rather than the state it is about to change (WP0.5).  A
        # no-op at the default delay of 0.
        ctx.capture_view()

        # If coderack is empty, repost initial codelets and re-clamp
        # initial slipnodes (Scheme: run.ss:155-157)
        if ctx.coderack.is_empty:
            self._post_initial_codelets()
            ctx.slipnet.clamp_initially_relevant(self.meta)

        # Select and execute a codelet
        codelet = ctx.coderack.choose_and_remove(
            ctx.temperature.value, ctx.rng
        )
        if codelet is None:
            return result

        ctx.codelet_count += 1
        ctx.coderack.current_time = ctx.codelet_count
        result.codelet_type = codelet.codelet_type
        result.codelet_count = ctx.codelet_count

        logger.info(
            "codelet #%d: %s (T=%.0f)",
            ctx.codelet_count,
            codelet.codelet_type,
            ctx.temperature.value,
        )
        if ctx.track_access and ctx.access is not None:
            ctx.access.begin()
            try:
                self._execute_codelet(codelet)
            finally:
                # Validated here, at the codelet's own commit point, and nowhere else.
                # A read-set means "these were the premises when I decided" and only
                # answers a question asked at the moment of committing; checked later it
                # is guaranteed to fail, because subsequent codelets have legitimately
                # moved on.  Serially this always passes — nothing runs in between —
                # which is exactly why tracking changes no serial behaviour.  Under
                # free-running a False here is the signal to fizzle.
                result.premises_held = ctx.access.validate()
                ctx.access.end()
        else:
            self._execute_codelet(codelet)

        self._emit_new_trace_events(ctx)
        ctx.sink.on_codelet(ctx, codelet, result)

        # A jootser may have decided the program is looping and given up
        # (§4.5.2 — "Metacat simply 'gives up' in a graceful manner and stops").
        if getattr(ctx, "_gave_up", False):
            self.status = STATUS_GAVE_UP
            ctx._gave_up = False  # type: ignore[attr-defined]
            result.gave_up = True
            self.finish()
            return result

        # Check if a codelet reported an answer
        pending = getattr(ctx, "_pending_answer", None)
        if pending is not None:
            result.answer_found = True
            result.answer = pending
            self.status = STATUS_ANSWER_FOUND
            self._answers.append(pending)
            ctx._pending_answer = None  # type: ignore[attr-defined]
            logger.info(">>> ANSWER FOUND: '%s' (quality=%.0f)", pending,
                        getattr(ctx, "_pending_answer_quality", 0))
            ctx.sink.on_answer(
                ctx, pending, float(getattr(ctx, "_pending_answer_quality", 0) or 0)
            )
            self.finish()

        # Check for update cycle
        ucl = self.meta.get_param("update_cycle_length", 15)
        if ctx.codelet_count % ucl == 0:
            self.update_everything()
            # ``update_everything`` records concept-activation events of its own, and
            # they arrive after the codelet has been reported.  Draining only once per
            # step, before this call, silently dropped every one of them.
            self._emit_new_trace_events(ctx)

        return result

    def _emit_new_trace_events(self, ctx: EngineContext) -> None:
        """Hand the sink every Trace event it has not seen yet.

        Driven from a watermark rather than a per-call diff so that calling it more
        often than necessary is free and calling it twice cannot double-report.  That
        matters because Trace events are recorded from several places — codelets, the
        Trace's own clamp and snag lifecycle, and the update cycle — and the emission
        points have to cover all of them without coordinating with each other.
        """
        events = ctx.trace.events
        if len(events) == self._trace_emitted:
            return
        for event in events[self._trace_emitted:]:
            ctx.sink.on_trace_event(ctx, event)
        self._trace_emitted = len(events)

    def finish(self) -> None:
        """Mark the Run stopped and emit ``on_turn_end`` exactly once.

        Normal mode's second complete-state capture, and where a buffering Audit sink
        flushes — so emitting it twice would double a Run's record, and not emitting it
        would lose the end of one.

        It is a method rather than a line at the bottom of ``run_mcat`` because a Run
        can stop in three different places: a codelet reports an answer, a jootser
        gives up, or the step budget runs out.  The service layer also drives runs one
        codelet per API request and never calls ``run_mcat`` at all, so it needs a way
        to say "this Run is over" itself.  The idempotence is what makes calling it
        from all of those safe.
        """
        if self._turn_ended or self.ctx is None:
            return
        # Anything recorded since the last drain — a final snag, an answer event —
        # must reach the sink before the Run's closing capture.
        self._emit_new_trace_events(self.ctx)
        self._turn_ended = True
        self.ctx.sink.on_turn_end(self.ctx)

    def _execute_codelet(self, codelet: Codelet) -> None:
        """Execute a single codelet via the CodeletInterpreter.

        Looks up the compiled program for this codelet type and executes
        it against the current EngineContext. If no program exists (empty
        execute_body), the codelet is a no-op.
        """
        compiled = self._registry.get_compiled(codelet.codelet_type)
        if compiled.is_empty:
            return
        self._interpreter.execute(compiled, self.ctx, **codelet.arguments)

    def run_mcat(self, max_steps: int = 0) -> RunResult:
        """Main loop: step until answer or limit.

        Scheme: run.ss run-mcat.
        """
        self.status = STATUS_RUNNING
        self.ctx.run_ended = False
        result = RunResult()

        step = 0
        while self.status == STATUS_RUNNING:
            if max_steps > 0 and step >= max_steps:
                self.status = STATUS_HALTED
                break

            step_result = self.step_mcat()
            result.steps.append(step_result)

            if step_result.answer_found:
                # ``step_mcat`` has already recorded the answer and set the status; it is
                # the single place a pending answer is collected, so appending again here
                # reported every answer twice (``RunResult.answers == ['ijl', 'ijl']``).
                self.status = STATUS_ANSWER_FOUND

            step += 1

        self.finish()
        result.status = self.status
        result.answers = list(self._answers)
        result.codelet_count = self.ctx.codelet_count if self.ctx else 0
        return result

    def update_everything(self) -> None:
        """Full update cycle — called every update_cycle_length codelets.

        Scheme: run.ss:295-315. Order matches the original:
        1.  check-if-rules-possible (run.ss:297)
        2.  update workspace values (strengths, importances, unhappiness)
        3.  snag-period stochastic exit (run.ss:299-302)
        4.  clamp-period expiration check (run.ss:303-304)
        5.  tick clamp expirations (slipnet + temperature — Python mechanism)
        6.  spread workspace → themespace
        7.  spread within themespace
        8.  update slipnet (theme→slipnet + decay + spread + jump)
        9.  update temperature
        10. post bottom-up codelets
        11. post top-down codelets
        """
        ctx = self.ctx
        if ctx is None:
            return
        # Bound here as well as in ``step_mcat`` because tests and the service layer
        # both call this directly.
        with use_allocator(ctx.ids):
            self._update_everything(ctx)

    def _update_everything(self, ctx: EngineContext) -> None:
        # 1. Check if rules are possible (Scheme: run.ss:297)
        ctx.workspace.check_if_rules_possible()

        # 2-3. Structure strengths, then object importances / unhappiness /
        #      salience, then the workspace-level averages (run.ss:306, 325-344).
        self._update_workspace_values(ctx.workspace)

        # 4. Snag-period stochastic exit (Scheme: run.ss:299-302)
        if ctx.trace.within_snag_period:
            progress = ctx.trace.progress_since_last_snag(ctx.workspace)
            if ctx.rng.prob(progress / 100.0):
                ctx.trace.undo_snag_condition(
                    ctx.themespace, ctx.slipnet, ctx.temperature, ctx.workspace,
                )

        # 5. Clamp-period expiration check (Scheme: run.ss:303-304)
        if ctx.trace.clamp_period_expired(ctx.codelet_count):
            ctx.trace.undo_last_clamp(
                ctx.themespace, ctx.slipnet, ctx.codelet_count, ctx.coderack,
            )

        # 6. Tick clamp expirations (Python mechanism for initial slipnode clamps)
        ctx.slipnet.tick_clamps()
        ctx.temperature.tick_clamp()

        # 7. Spread activation from workspace to themespace
        if ctx.self_watching_enabled:
            self._spread_activation_to_themespace()

        # 8. Spread activation within themespace
        if ctx.self_watching_enabled:
            ctx.themespace.spread_activation()

        # 9. Update slipnet: theme→slipnet, then internal spreading
        #    (Scheme: slipnet.ss:377-389 — themes spread first, then decay+spread+jump)
        if ctx.self_watching_enabled:
            ctx.themespace.spread_activation_to_slipnet(ctx.slipnet, ctx.rng)
        threshold = getattr(ctx, "spreading_activation_threshold", 100)
        activations_before = {
            name: node.activation for name, node in ctx.slipnet.nodes.items()
        }
        ctx.slipnet.update_activations(ctx.rng, threshold=threshold)
        self._record_concept_activation_events(activations_before)

        # 10. Update temperature.  The rule factor asks whether a rule is both
        #     *possible* and supported — and in justify mode, for both pairs
        #     (formulas.ss:65-75), not merely whether some supported rule exists.
        avg_unhappiness = ctx.workspace.get_average_unhappiness()
        ctx.temperature.update(
            avg_unhappiness, ctx.workspace.rule_established(), ctx.meta
        )
        # ``get-removal-weight`` (``coderack.ss:237-240``) reads the global
        # ``*temperature*`` at eviction time.  Petacat's Coderack has to be told,
        # and the posting burst below is the one place a codelet is evicted
        # *after* the temperature has moved but *before* the next selection would
        # refresh it, so hand it over here.
        ctx.coderack.current_temperature = ctx.temperature.value

        # 11-12. Post the cycle's codelets — bottom-up, then top-down, then
        # thematic (``run.ss:317-319``, ``coderack.ss:553-572``) — as one
        # deferred batch.  The order matters because the batch's members never
        # evict each other but a *later* cycle's do: whichever types are posted
        # last are the ones the next cycle's overflow finds youngest.
        batch: list[Codelet] = []
        self._post_bottom_up_codelets(batch)
        self._post_top_down_codelets(batch)
        self._post_thematic_codelets(batch)
        ctx.coderack.post_deferred(batch, ctx.codelet_count, ctx.rng)

    def _record_concept_activation_events(
        self, activations_before: dict[str, float]
    ) -> None:
        """Note when a deep concept's activation moves substantially.

        §4.4: "nodes in the Slipnet monitor their own levels of activation,
        adding new concept-activation events to the Trace whenever sufficiently
        large changes occur in the activations of deep concepts.  The importance
        of this type of event is a function of a node's conceptual depth and of
        the magnitude of its activation change, with larger changes to deeper
        concepts being more important."

        This is the *sampled* half of the mechanism, run at cycle boundaries.  The
        other half is immediate: a concept-pattern clamp reports its own deltas
        through ``trace.make_concept_activation_monitor``, because a clamp's change
        would otherwise net out against the decay that follows it before this sampler
        ever looked.  Both use ``trace.concept_activation_importance``, so they cannot
        disagree about what counts as important.
        """
        ctx = self.ctx
        if ctx is None:
            return
        threshold = self.meta.get_param("concept_activation_importance_threshold", 85)
        for name, node in ctx.slipnet.nodes.items():
            before = activations_before.get(name, 0.0)
            # ``trace.ss:1345-1348``: ``(100* (* (% (abs delta)) (% (cd slipnode))))``
            # — a **product** of the magnitude of the change and the concept's depth,
            # over the **absolute** change.  An average lets a shallow concept through
            # on a large jump, which is the opposite of "larger changes to deeper
            # concepts being more important"; and ignoring decreases hid the
            # deactivation of a dominant concept, which is as much a milestone as its
            # activation was.
            if concept_activation_importance(node, before, node.activation) >= threshold:
                ctx.trace.record_event(
                    TraceEvent(
                        event_type=CONCEPT_ACTIVATION,
                        codelet_count=ctx.codelet_count,
                        temperature=ctx.temperature.value,
                        description=f"the concept of {node.short_name} became active",
                    )
                )

    def _spread_activation_to_themespace(self) -> None:
        """Boost themes from every built bridge.

        Scheme: ``boost-themes`` (bridges.ss:296-313), driven from
        ``spread-activation-to-themespace`` (workspace.ss:495-498).  Spanning
        bridges boost twice as hard, since they characterise whole strings.
        """
        ctx = self.ctx
        if ctx is None:
            return

        all_bridges = (
            ctx.workspace.top_bridges
            + ctx.workspace.bottom_bridges
            + ctx.workspace.vertical_bridges
        )
        for bridge in all_bridges:
            if not bridge.is_built:
                continue
            factor = bridge.strength * (2 if bridge.is_spanning_bridge else 1)
            for dimension, relation in bridge.get_associated_thematic_relations():
                ctx.themespace.boost_theme(
                    bridge.theme_type, dimension, relation, factor
                )

    def _post_bottom_up_codelets(self, batch: list[Codelet] | None = None) -> None:
        """Collect the cycle's bottom-up codelets into *batch*.

        Scheme: ``add-bottom-up-codelets`` (coderack.ss:565-572), 465-550.
        Each codelet type has a posting probability (from workspace state)
        and a count (from workspace state). Stochastically decide whether
        to post, then post the computed number.
        """
        ctx = self.ctx
        if ctx is None:
            return
        if batch is None:
            batch = []
            deferred = True
        else:
            deferred = False

        time = ctx.codelet_count

        # All bottom-up codelet types (matches original *bottom-up-codelet-types*)
        bottom_up_types = [
            "bottom-up-bond-scout",
            "group-scout:whole-string",
            "bottom-up-bridge-scout",
            "important-object-bridge-scout",
            "bottom-up-description-scout",
            "rule-scout",
            "answer-finder",
            "answer-justifier",
            "progress-watcher",
            "jootser",
            "breaker",
        ]

        for codelet_type in bottom_up_types:
            # Skip types inappropriate for current mode
            if ctx.justify_mode and codelet_type == "answer-finder":
                continue
            if not ctx.justify_mode and codelet_type == "answer-justifier":
                continue
            if not ctx.self_watching_enabled and codelet_type in (
                "progress-watcher", "jootser",
            ):
                continue

            post_prob = self._compute_posting_probability(codelet_type)
            if not ctx.rng.prob(post_prob):
                continue

            urgency = self._compute_bottom_up_urgency(codelet_type)
            num = self._compute_num_to_post(codelet_type)

            for _ in range(num):
                batch.append(Codelet(codelet_type, urgency, time_stamp=time))

        if deferred:
            ctx.coderack.post_deferred(batch, time, ctx.rng)

    def _post_thematic_codelets(self, batch: list[Codelet] | None = None) -> None:
        """Collect the cycle's thematic codelets into *batch*.

        Scheme: the second half of ``add-top-down-codelets``
        (coderack.ss:557-562) — thematic types are posted *after* the top-down
        slipnodes, not before either of them, which is where this used to sit.
        """
        ctx = self.ctx
        if ctx is None or not ctx.self_watching_enabled:
            return
        if batch is None:
            batch = []
            deferred = True
        else:
            deferred = False

        thematic_type = "thematic-bridge-scout"
        post_prob = self._compute_posting_probability(thematic_type)
        if ctx.rng.prob(post_prob):
            urgency = round(ctx.themespace.get_max_positive_theme_activation())
            num = self._compute_num_to_post(thematic_type)
            for _ in range(num):
                batch.append(
                    Codelet(thematic_type, urgency, time_stamp=ctx.codelet_count)
                )

        if deferred:
            ctx.coderack.post_deferred(batch, ctx.codelet_count, ctx.rng)

    def _compute_posting_probability(self, codelet_type: str) -> float:
        """Compute the probability of posting a codelet of this type.

        Scheme: coderack.ss:465-515.
        """
        ctx = self.ctx
        if ctx is None:
            return 0.0

        ws = ctx.workspace

        # ``post-codelet-probability`` (``coderack.ss:470-473``) consults the codelet
        # type's clamp *before* any workspace-driven computation: a clamped type posts
        # at ``clamped-urgency/100`` and the Workspace has no say.  That is what turns
        # a clamp into a redirection of the whole system — the rule-codelet clamp posts
        # rule work at 0.77/0.91 and everything else at 0.21 — rather than a nudge.
        # (The mode exclusions that return 0 in the Scheme are applied by the callers,
        # before they get here, so this is the right place for the clamp check.)
        clamped = ctx.coderack.clamped_posting_probability(codelet_type)
        if clamped is not None:
            return clamped

        if codelet_type in (
            "bottom-up-bond-scout",
            "top-down-bond-scout:category",
            "top-down-bond-scout:direction",
            "top-down-group-scout:category",
            "top-down-group-scout:direction",
            "group-scout:whole-string",
        ):
            return ws.get_average_intra_string_unhappiness() / 100.0

        if codelet_type in ("bottom-up-bridge-scout", "important-object-bridge-scout"):
            # ``coderack.ss:482-484`` — over top and vertical, plus bottom when
            # justifying.  No "are there any bridges yet" guard: with no bridges
            # every object is maximally unhappy and the strength reaches 0 by
            # arithmetic.
            return (100.0 - ws.get_min_mapping_strength()) / 100.0

        if codelet_type in ("bottom-up-description-scout", "top-down-description-scout"):
            return ws.get_average_unhappiness() / 100.0

        if codelet_type == "rule-scout":
            # ``coderack.ss:488-491``: half probability while no rule type is
            # possible, full once one is.  Bonds have nothing to do with it — the
            # question is whether rule-describable bridges cover a whole pair.
            return 0.5 if not ws.get_possible_rule_types() else 1.0

        if codelet_type == "answer-finder":
            if ws.has_supported_rule():
                return (100.0 - ctx.temperature.value) / 100.0
            return 0.0

        if codelet_type == "answer-justifier":
            top = ws.get_supported_rules(True)
            bottom = ws.get_supported_rules(False)
            if top or bottom:
                return (100.0 - ctx.temperature.value) / 100.0
            return 0.0

        if codelet_type == "breaker":
            return ctx.temperature.value / 100.0

        if codelet_type == "progress-watcher":
            return 1.0 if ctx.themespace.has_thematic_pressure() else 0.25

        if codelet_type == "jootser":
            if ctx.trace.within_snag_period or ctx.trace.within_clamp_period:
                return 0.4
            return 0.1

        if codelet_type == "thematic-bridge-scout":
            return ctx.themespace.get_max_positive_theme_activation() / 100.0

        return 0.5  # Default

    def _compute_num_to_post(self, codelet_type: str) -> int:
        """Compute how many codelets to post.

        Scheme: ``num-of-codelets-to-post`` (``coderack.ss:517-550``).

        The three scout families count objects against *stochastically blurred*
        absolute thresholds (``rough-num-of-objects``), not against fixed ratios
        of the object population.  Called only after the posting probability has
        already passed, exactly as the reference's ``stochastic-if*`` orders it,
        so the extra ``~`` draws land in the same place in the random stream.
        """
        ctx = self.ctx
        if ctx is None:
            return 1

        ws = ctx.workspace

        if codelet_type in (
            "bottom-up-bond-scout",
            "top-down-bond-scout:category",
            "top-down-bond-scout:direction",
        ):
            return {"few": 2, "some": 4, "many": 6}[
                ws.get_rough_num_of_unrelated_objects(ctx.rng)
            ]

        if codelet_type in (
            "top-down-group-scout:category",
            "top-down-group-scout:direction",
            "group-scout:whole-string",
        ):
            if not any(s.bonds for s in ws.all_strings):
                return 0
            return {"few": 1, "some": 2, "many": 3}[
                ws.get_rough_num_of_ungrouped_objects(ctx.rng)
            ]

        if codelet_type in ("bottom-up-bridge-scout", "important-object-bridge-scout"):
            return {"few": 2, "some": 5, "many": 6}[
                ws.get_rough_num_of_unmapped_objects(ctx.rng)
            ]

        if codelet_type in ("bottom-up-description-scout", "top-down-description-scout"):
            return 2

        if codelet_type == "rule-scout":
            # ``coderack.ss:542``: two scouts per possible rule type, at least one.
            return max(1, 2 * len(ws.get_possible_rule_types()))

        if codelet_type == "thematic-bridge-scout":
            # ``coderack.ss:547-549``: ``(round (* 10 (% max-inter-string-unhappiness)))``.
            # The *mapping* deficit, and no floor — thematic scouts are the vehicle
            # of clamped-theme pressure, and with the mappings settled the
            # reference posts none.  Reading intra-string unhappiness instead
            # posted one scout where the reference posts up to ten, precisely
            # during a clamp episode: a snag response leaves the strings
            # well-bonded and the mappings in ruins.
            return round(10 * ws.get_max_inter_string_unhappiness() / 100.0)

        if codelet_type == "progress-watcher":
            return 2

        if codelet_type == "jootser":
            return 2 if not ctx.justify_mode else 1

        # answer-finder, answer-justifier, breaker: 1
        return 1

    def _compute_bottom_up_urgency(self, codelet_type: str) -> int:
        """Compute urgency for bottom-up codelets.

        Scheme: coderack.ss:575-590.
        """
        ctx = self.ctx
        if ctx is None:
            return 35

        if codelet_type in ("answer-finder", "answer-justifier"):
            return max(1, round(100 - ctx.temperature.value))

        if codelet_type == "breaker":
            return self.meta.get_urgency("extremely_low")

        # ``coderack.ss:581-582``: the two self-watching codelets take *medium*
        # urgency, not the ``else`` branch's low.
        if codelet_type in ("progress-watcher", "jootser"):
            return self.meta.get_urgency("medium")

        # Most bottom-up scouts use low urgency
        return self.meta.get_urgency("low")

    def _post_top_down_codelets(self, batch: list[Codelet] | None = None) -> None:
        """Collect the cycle's top-down codelets into *batch*.

        Scheme: ``add-top-down-codelets`` (coderack.ss:553-556), slipnet.ss:212-222.
        Each top-down codelet receives the triggering slipnode as an argument
        so it can guide its search (e.g., look for successor bonds specifically).
        """
        ctx = self.ctx
        if ctx is None:
            return
        if batch is None:
            batch = []
            deferred = True
        else:
            deferred = False

        top_down_nodes = self.meta.get_param("top_down_slipnodes", [])
        threshold = self.meta.get_param("full_activation_threshold", 50)

        for node_name in top_down_nodes:
            node = ctx.slipnet.nodes.get(node_name)
            # ``above-threshold?`` (>= 50), not ``fully-active?`` (== 100).
            # Top-down posting is the *only* consumer of the weaker predicate in
            # the reference (slipnet.ss:212-213); everything else asks for
            # saturation.
            if node is None or not node.above_threshold(threshold):
                continue

            # Compute urgency from conceptual depth and activation
            urgency = round(node.conceptual_depth * node.activation / 100.0)

            # Determine which codelets to post for this node
            for rule in self.meta.posting_rules:
                if rule.direction != "top_down":
                    continue
                if rule.triggering_slipnodes and node_name not in rule.triggering_slipnodes:
                    continue

                # Stochastic posting based on workspace state
                post_prob = self._compute_posting_probability(rule.codelet_type)
                if not ctx.rng.prob(post_prob):
                    continue

                num = self._compute_num_to_post(rule.codelet_type)
                for _ in range(num):
                    batch.append(
                        Codelet(
                            rule.codelet_type,
                            urgency,
                            arguments={"slipnode": node},
                            time_stamp=ctx.codelet_count,
                        )
                    )

        if deferred:
            ctx.coderack.post_deferred(batch, ctx.codelet_count, ctx.rng)

    def __repr__(self) -> str:
        ctx_info = ""
        if self.ctx:
            ctx_info = f", codelets={self.ctx.codelet_count}"
        return f"EngineRunner(status={self.status}{ctx_info})"
