"""Engine Runner — main control loop.

Orchestrates init_mcat, step_mcat, run_mcat, update_everything.

Scheme source: run.ss
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("petacat.engine")

from server.engine.codelet_dsl.builtins import get_builtins
from server.engine.commentary import CommentaryLog, emit_new_problem
from server.engine.codelet_dsl.interpreter import CodeletInterpreter, CodeletRegistry
from server.engine.coderack import Codelet, Coderack
from server.engine.memory import EpisodicMemory
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.engine.slipnet import Slipnet
from server.engine.temperature import Temperature
from server.engine.themes import Themespace
from server.engine.trace import TemporalTrace, TraceEvent
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
        commentary: CommentaryLog,
        rng: RNG,
        meta: MetadataProvider,
    ) -> None:
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
        self.codelet_count: int = 0
        self.justify_mode: bool = False
        self.self_watching_enabled: bool = True
        self.spreading_activation_threshold: int = 100


class EngineRunner:
    """The main engine runner."""

    def __init__(self, meta: MetadataProvider) -> None:
        self.meta = meta
        self.ctx: EngineContext | None = None
        self.status: str = STATUS_INITIALIZED
        self._answers: list[str] = []

        # Build the codelet interpreter and registry
        self._interpreter = CodeletInterpreter(builtins=get_builtins())
        self._registry = CodeletRegistry.from_metadata(meta, self._interpreter)

    def init_mcat(
        self,
        initial: str,
        modified: str,
        target: str,
        answer: str | None = None,
        seed: int = 0,
        memory: EpisodicMemory | None = None,
    ) -> None:
        """Initialize Metacat for a new run.

        Scheme: run.ss init-mcat.
        """
        rng = RNG(seed)

        # Configure class-level thematic weight from formula coefficients
        WorkspaceStructure.configure_thematic_weight(self.meta)

        # Build slipnet from metadata
        slipnet = Slipnet.from_metadata(self.meta)

        # Create workspace
        workspace = Workspace(initial, modified, target, answer, slipnet)

        # Create coderack
        coderack = Coderack(self.meta)

        # Create themespace
        themespace = Themespace(self.meta)

        # Create trace
        trace = TemporalTrace()

        # Use provided or new memory
        if memory is None:
            memory = EpisodicMemory()

        # Create temperature
        temperature = Temperature(
            initial=float(self.meta.get_param("initial_temperature", 100))
        )

        # Create commentary log
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

        # Clamp initially relevant slipnet nodes
        slipnet.clamp_initially_relevant(self.meta)

        # Post initial codelets
        self._post_initial_codelets()

        self.status = STATUS_INITIALIZED
        self._answers = []

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

    def _post_initial_codelets(self) -> None:
        """Post initial bottom-up scout codelets.

        Scheme: run.ss — 2 * num_objects codelets, half bond scouts, half bridge scouts.
        """
        ctx = self.ctx
        if ctx is None:
            return

        num_objects = len(ctx.workspace.all_objects)
        urgency = self.meta.get_urgency("very_low")

        for _ in range(num_objects):
            ctx.coderack.post(
                Codelet("bottom-up-bond-scout", urgency, time_stamp=0)
            )
            ctx.coderack.post(
                Codelet("bottom-up-bridge-scout", urgency, time_stamp=0)
            )

    def step_mcat(self) -> StepResult:
        """Execute one codelet.

        Scheme: run.ss step-mcat.
        """
        ctx = self.ctx
        if ctx is None:
            return StepResult()

        result = StepResult()

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
        result.codelet_type = codelet.codelet_type
        result.codelet_count = ctx.codelet_count

        logger.info(
            "codelet #%d: %s (T=%.0f)",
            ctx.codelet_count,
            codelet.codelet_type,
            ctx.temperature.value,
        )
        self._execute_codelet(codelet)

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

        # Check for update cycle
        ucl = self.meta.get_param("update_cycle_length", 15)
        if ctx.codelet_count % ucl == 0:
            self.update_everything()

        return result

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
        result = RunResult()

        step = 0
        while self.status == STATUS_RUNNING:
            if max_steps > 0 and step >= max_steps:
                self.status = STATUS_HALTED
                break

            step_result = self.step_mcat()
            result.steps.append(step_result)

            if step_result.answer_found:
                self._answers.append(step_result.answer or "")
                self.status = STATUS_ANSWER_FOUND

            step += 1

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

        # 1. Check if rules are possible (Scheme: run.ss:297)
        ctx.workspace.check_if_rules_possible()

        # 2. Update all structure strengths
        ctx.workspace.update_all_structure_strengths()

        # 3. Update object importances, unhappiness, salience
        ctx.workspace.update_all_object_values()

        # 4. Snag-period stochastic exit (Scheme: run.ss:299-302)
        if ctx.trace.within_snag_period:
            progress = ctx.trace.progress_since_last_snag()
            if ctx.rng.prob(progress / 100.0):
                ctx.trace.undo_snag_condition(
                    ctx.themespace, ctx.slipnet, ctx.temperature,
                )

        # 5. Clamp-period expiration check (Scheme: run.ss:303-304)
        if ctx.trace.clamp_period_expired(ctx.codelet_count):
            ctx.trace.undo_last_clamp(
                ctx.themespace, ctx.slipnet, ctx.codelet_count,
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
        ctx.slipnet.update_activations(ctx.rng, threshold=threshold)

        # 10. Update temperature
        avg_unhappiness = ctx.workspace.get_average_unhappiness()
        has_rule = ctx.workspace.has_supported_rule()
        ctx.temperature.update(avg_unhappiness, has_rule, ctx.meta)

        # 11. Post new bottom-up codelets
        self._post_bottom_up_codelets()

        # 12. Post new top-down codelets
        self._post_top_down_codelets()

    def _spread_activation_to_themespace(self) -> None:
        """Boost themes from bridge concept-mappings.

        Scheme: workspace.ss:495-498 (spread-activation-to-themespace).
        Each built bridge extracts its theme pattern and boosts the
        corresponding themes in the Themespace.
        """
        ctx = self.ctx
        if ctx is None:
            return

        from server.engine.bridges import BRIDGE_TOP, BRIDGE_BOTTOM, BRIDGE_VERTICAL
        from server.engine.themes import THEME_TOP_BRIDGE, THEME_BOTTOM_BRIDGE, THEME_VERTICAL_BRIDGE

        bt_to_tt = {
            BRIDGE_TOP: THEME_TOP_BRIDGE,
            BRIDGE_BOTTOM: THEME_BOTTOM_BRIDGE,
            BRIDGE_VERTICAL: THEME_VERTICAL_BRIDGE,
        }

        all_bridges = (
            ctx.workspace.top_bridges
            + ctx.workspace.bottom_bridges
            + ctx.workspace.vertical_bridges
        )
        for bridge in all_bridges:
            if not bridge.is_built:
                continue
            theme_type = bt_to_tt.get(bridge.bridge_type)
            if theme_type is None:
                continue
            pattern = bridge.get_theme_pattern()
            for dimension, relation in pattern.items():
                ctx.themespace.boost_theme(
                    theme_type, dimension, relation, bridge.strength
                )

    def _post_bottom_up_codelets(self) -> None:
        """Post bottom-up codelets based on workspace state.

        Scheme: coderack.ss:565-572, 465-550.
        Each codelet type has a posting probability (from workspace state)
        and a count (from workspace state). Stochastically decide whether
        to post, then post the computed number.
        """
        ctx = self.ctx
        if ctx is None:
            return

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
                ctx.coderack.post(
                    Codelet(codelet_type, urgency, time_stamp=time)
                )

        # Thematic codelet types
        if ctx.self_watching_enabled:
            thematic_type = "thematic-bridge-scout"
            post_prob = self._compute_posting_probability(thematic_type)
            if ctx.rng.prob(post_prob):
                urgency = round(ctx.themespace.get_max_positive_theme_activation())
                num = self._compute_num_to_post(thematic_type)
                for _ in range(num):
                    ctx.coderack.post(
                        Codelet(thematic_type, urgency, time_stamp=time)
                    )

    def _compute_posting_probability(self, codelet_type: str) -> float:
        """Compute the probability of posting a codelet of this type.

        Scheme: coderack.ss:465-515.
        """
        ctx = self.ctx
        if ctx is None:
            return 0.0

        ws = ctx.workspace

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
            min_strength = min(
                ws.get_mapping_strength("top"),
                ws.get_mapping_strength("vertical"),
            ) if ws.top_bridges or ws.vertical_bridges else 0.0
            return (100.0 - min_strength) / 100.0

        if codelet_type in ("bottom-up-description-scout", "top-down-description-scout"):
            return ws.get_average_unhappiness() / 100.0

        if codelet_type == "rule-scout":
            has_bonds = any(s.bonds for s in ws.all_strings)
            return 1.0 if has_bonds else 0.5

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

        Scheme: coderack.ss:518-550.
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
            unrelated = sum(s.get_num_unrelated_objects() for s in ws.all_strings)
            total = max(1, len(ws.all_objects))
            ratio = unrelated / total
            if ratio < 0.2:
                return 2
            elif ratio < 0.5:
                return 4
            return 6

        if codelet_type in (
            "top-down-group-scout:category",
            "top-down-group-scout:direction",
            "group-scout:whole-string",
        ):
            if not any(s.bonds for s in ws.all_strings):
                return 0
            ungrouped = sum(s.get_num_ungrouped_objects() for s in ws.all_strings)
            total = max(1, len(ws.all_objects))
            ratio = ungrouped / total
            if ratio < 0.2:
                return 1
            elif ratio < 0.5:
                return 2
            return 3

        if codelet_type in ("bottom-up-bridge-scout", "important-object-bridge-scout"):
            unmapped = ws.get_num_unmapped_objects()
            total = max(1, len(ws.all_objects))
            ratio = unmapped / total
            if ratio < 0.2:
                return 2
            elif ratio < 0.5:
                return 5
            return 6

        if codelet_type in ("bottom-up-description-scout", "top-down-description-scout"):
            return 2

        if codelet_type == "rule-scout":
            has_bonds = any(s.bonds for s in ws.all_strings)
            return max(1, 2) if has_bonds else 1

        if codelet_type == "thematic-bridge-scout":
            max_unhappy = max(
                (s.get_average_intra_string_unhappiness() for s in ws.all_strings),
                default=100.0,
            )
            return max(1, round(10 * max_unhappy / 100.0))

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

        # Most bottom-up scouts use low urgency
        return self.meta.get_urgency("low")

    def _post_top_down_codelets(self) -> None:
        """Post top-down codelets driven by active slipnet nodes.

        Scheme: run.ss add-top-down-codelets, slipnet.ss:212-222.
        Each top-down codelet receives the triggering slipnode as an argument
        so it can guide its search (e.g., look for successor bonds specifically).
        """
        ctx = self.ctx
        if ctx is None:
            return

        top_down_nodes = self.meta.get_param("top_down_slipnodes", [])
        threshold = self.meta.get_param("full_activation_threshold", 50)

        for node_name in top_down_nodes:
            node = ctx.slipnet.nodes.get(node_name)
            if node is None or not node.fully_active(threshold):
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
                    ctx.coderack.post(
                        Codelet(
                            rule.codelet_type,
                            urgency,
                            arguments={"slipnode": node},
                            time_stamp=ctx.codelet_count,
                        )
                    )

    def __repr__(self) -> str:
        ctx_info = ""
        if self.ctx:
            ctx_info = f", codelets={self.ctx.codelet_count}"
        return f"EngineRunner(status={self.status}{ctx_info})"
