"""Verbose mode -- Metacat's running narration of what its codelets do.

Metacat prints this narration to the Interaction window when the Options menu's
"Verbose mode" is checked (``gui.ss:664``, ``%verbose%``).  About 250 ``say``,
``vprintf`` and ``vprint`` calls through ``bonds.ss``, ``bridges.ss``, ``groups.ss``,
``jootsing.ss``, ``justify.ss``, ``themes.ss``, ``answers.ss``, ``descriptions.ss``,
``rules.ss``, ``breakers.ss``, ``trace.ss`` and ``run.ss`` do it, and every codelet
procedure opens with a dashed line and ``In <type> codelet...``
(``define-codelet-procedure*``, ``syntactic-sugar.ss:245``).  The help text says the
messages are for debugging and "slow down the program considerably"
(``help.txt:75``).

Where things live
-----------------
* **The English** is in the Metacat Standard Configuration's ``commentary_templates.json``
  under ``verbose_messages``,
  one entry per distinct message, keyed by a name and written with ``{}`` where the
  Scheme prints an argument.  It is the same file, the same ``MetadataProvider`` field
  and the same database row as every other phrase the engine writes, so there is one
  place to read and edit the prose.
* **The call sites** are the Scheme's: a codelet body says ``if verbose: say("chose-object", x)``
  at the point the Scheme's ``say`` is, and a Python procedure says
  ``if ctx.verbose: ctx.verbose_log.say("chose-object", x)``.  The guard is the whole cost when
  Verbose mode is off: one attribute read and one branch, with no argument evaluated
  and no string built, which is what Metacat's ``(if* %verbose% ...)`` macros do.
* **The names of objects** (``ascii-name``, ``generic-name``, ``print-name`` and each
  object's ``print`` method) are written here, once, from the same definitions the
  Trace display, the snag explanation and the rule English already follow.

What it must never do
---------------------
It reads, never writes.  No function here draws a random number, activates a node or
changes a structure, so a run is the same run with Verbose mode on or off (the lockstep
replay is identical both ways).  The buffer is bounded; the oldest lines fall off.

Metacat's GUI-only variations are those of the headless build that the lockstep harness
records: ``%workspace-graphics%`` is off, so a structure prints ``(proposed)`` and never
``(proposed, not drawn)``, and a vertical bridge never prints its label number.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider

#: How many lines the log keeps.  The narration of a run is about ten lines per codelet,
#: so this is a few hundred codelets: enough to read the recent past, small enough that
#: a run left on Verbose mode for hours holds a constant amount of memory.
DEFAULT_CAPACITY = 5000

DASHES = "-" * 46

#: Step mode narrates a step of at most this many codelets (``run.ss:47``:
#: ``(not (> %step-cycles% 10))``).
VERBOSE_STEP_LIMIT = 10


# ---------------------------------------------------------------------------
# How Scheme prints a value (``printf "~a"``)
# ---------------------------------------------------------------------------


def _float(x: float) -> str:
    """Chez Scheme's ``display`` of a flonum: ``0.5``, ``10.0``, ``1e-5``, ``+inf.0``."""
    if x != x:
        return "+nan.0"
    if x in (float("inf"), float("-inf")):
        return "+inf.0" if x > 0 else "-inf.0"
    text = repr(x)
    if "e" in text:
        mantissa, _, exponent = text.partition("e")
        if mantissa.endswith(".0"):
            mantissa = mantissa[:-2]
        text = f"{mantissa}e{int(exponent)}"
    return text


def exact(x: Any) -> Any:
    """A value Metacat computes with ``round`` -- an exact integer there -- as one here.

    Petacat keeps the same quantities as floats, and Scheme prints ``100`` for the exact
    integer and ``100.0`` for the flonum.
    """
    if isinstance(x, float) and x == x and x not in (float("inf"), float("-inf")) and x == int(x):
        return int(x)
    return x


def display(x: Any) -> str:
    """``(printf "~a" x)`` for everything a verbose message prints."""
    if isinstance(x, str):
        return x
    if x is True:
        return "#t"
    if x is False or x is None:
        return "#f"
    if isinstance(x, float):
        return _float(x)
    if isinstance(x, int):
        return str(x)
    if isinstance(x, (list, tuple)):
        return "(" + " ".join(display(i) for i in x) + ")"
    if hasattr(x, "numerator") and hasattr(x, "denominator"):  # Fraction
        return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"
    return say_name(x)


def round_to_100ths(n: float) -> float:
    """``round-to-100ths`` (``utilities.ss:258``)."""
    return float(round(n * 100)) / 100.0


# ---------------------------------------------------------------------------
# Names -- the ``print-name``, ``ascii-name`` and ``generic-name`` messages
# ---------------------------------------------------------------------------


def _node_name(node: Any) -> str:
    """``get-lowercase-name``: the symbol without ``plato-``, lower-cased."""
    from server.engine.trace_display import lowercase_name

    return lowercase_name(node)


label_name = _node_name


def _short(node: Any) -> str:
    return str(getattr(node, "short_name", None) or getattr(node, "name", "?"))


def generic_name(string: Any) -> str:
    """``generic-name`` of a workspace string (``workspace-strings.ss:76``)."""
    translated = "translated " if getattr(string, "translated", False) else ""
    return f"{translated}{string.string_type} string"


def group_letter_name(group: Any) -> str | None:
    """The group's ``print-name`` as ``make-group`` sets it (``groups.ss:50-56``).

    Only a sameness group over the letter-category facet is named, by its letter in
    upper case; every other group is named by direction or length in ``ascii_name``.
    """
    facet = getattr(group, "bond_facet", None)
    if getattr(facet, "name", "") != "plato-letter-category":
        return None
    if getattr(getattr(group, "group_category", None), "name", "") != "plato-samegrp":
        return None
    initial = group._get_initial_letter_category()
    if initial is None:
        return None
    return _node_name(initial).upper()


def ascii_name(obj: Any) -> str:
    """``ascii-name`` of a string, letter or group (``workspace-objects.ss:34``, ``groups.ss:118``)."""
    from server.engine.workspace import WorkspaceString

    if isinstance(obj, WorkspaceString):
        return f'"{obj.text}"'
    if hasattr(obj, "objects"):  # group
        label = group_letter_name(obj)
        if label is None:
            direction = getattr(getattr(obj, "direction", None), "name", None)
            if direction == "plato-right":
                label = ">"
            elif direction == "plato-left":
                label = "<"
            else:
                label = str(len(obj.objects))
        span = obj.right_string_pos - obj.left_string_pos + 1
        whole = span == obj.string.length
        where = "*" if whole else f"{obj.left_string_pos},{obj.right_string_pos}"
        return f"[{label}]:{where}"
    return f"{_node_name(obj.letter_category)}:{obj.left_string_pos}"


def object_print_name(obj: Any) -> str:
    """``print-name`` of an object ``say`` is given (``say-object``, ``utilities.ss:169``)."""
    from server.engine.trace_display import concept_mapping_print_name

    if hasattr(obj, "descriptor1") and hasattr(obj, "descriptor2"):
        return concept_mapping_print_name(obj)
    if hasattr(obj, "description_type") and hasattr(obj, "descriptor"):
        return f"{_short(obj.description_type)}:{_short(obj.descriptor)}"
    if hasattr(obj, "short_name"):
        return str(obj.short_name)
    return ascii_name(obj)


def say_name(obj: Any) -> str:
    return object_print_name(obj)


def full_object_name(obj: Any) -> str:
    """``full-workspace-object-name`` (``trace.ss:1298``)."""
    from server.engine.trace_display import _full_object_name

    return _full_object_name(obj)


_LEVEL_WORDS = {"proposed": "proposed", "evaluated": "evaluated"}


def level_suffix(structure: Any, level: str | None = None) -> str:
    """`` (new)``, `` (proposed)`` or `` (evaluated)``; nothing once built.

    Metacat's structures are *new* between construction and ``update-proposal-level``,
    a state Petacat's structures do not have: a call site that prints one in that
    moment says so with ``level="new"``.
    """
    if level is None:
        level = getattr(structure, "proposal_level", "built")
    if level == "built":
        return ""
    return f" ({_LEVEL_WORDS.get(level, level)})"


# ---------------------------------------------------------------------------
# What ``(print x)`` writes -- each object's ``print`` message
# ---------------------------------------------------------------------------


def concept_mapping_long_name(cm: Any) -> str:
    """``long-name`` (``concept-mappings.ss:56``)."""
    if getattr(cm, "is_identity", False) or getattr(cm, "identity", False):
        head = "CM"
    elif getattr(cm, "object1", None) == "coattail":
        head = "COATTAIL SLIPPAGE"
    else:
        head = "SLIPPAGE"
    label = getattr(cm, "label", None)
    if label is None or getattr(label, "name", "") == "plato-identity":
        arrow = "=>"
    else:
        arrow = f"=({_short(label)})=>"
    return f"{head} {_short(cm.description_type1)}:{_short(cm.descriptor1)}{arrow}{_short(cm.descriptor2)}"


def print_text(obj: Any, level: str | None = None, slipnet: Any = None) -> str:
    """The text of Metacat's ``(tell obj 'print)`` -- ends in a newline.

    ``level`` overrides the proposal level a structure is said to be at (see
    :func:`level_suffix`).  Lists are flattened and printed element by element, as the
    ``print`` procedure of ``utilities.ss:162`` does; anything that is not an object
    prints with ``~a``.
    """
    if isinstance(obj, (list, tuple)):
        return "".join(print_text(o, level, slipnet) for o in obj)
    if not hasattr(obj, "__dict__") or isinstance(obj, (str, int, float)):
        return display(obj) + "\n"
    from server.engine.bonds import Bond
    from server.engine.bridges import Bridge
    from server.engine.descriptions import Description
    from server.engine.rules import Rule
    from server.engine.workspace import WorkspaceString

    if isinstance(obj, WorkspaceString):
        prefix = "Translated " if getattr(obj, "translated", False) else ""
        return f'{prefix}Workspace string "{obj.text}"\n'
    if isinstance(obj, Bond):
        return _bond_text(obj, level)
    if isinstance(obj, Bridge):
        return _bridge_text(obj, level)
    if isinstance(obj, Description):
        return _description_text(obj, level)
    if isinstance(obj, Rule):
        return _rule_text(obj, unscored=level == "unscored")
    if hasattr(obj, "descriptor1") and hasattr(obj, "descriptor2"):
        return concept_mapping_long_name(obj) + "\n"
    if hasattr(obj, "left_string_pos"):
        return _object_text(obj, level)
    if hasattr(obj, "theme_type") and hasattr(obj, "dimension") and hasattr(obj, "activation"):
        return _theme_text(obj, slipnet)
    printer = getattr(obj, "verbose_text", None)
    if printer is not None:
        return printer()
    return display(obj) + "\n"


def _object_text(obj: Any, level: str | None) -> str:
    """``print`` of a letter or group (``workspace-objects.ss:101``)."""
    text = f"{full_object_name(obj)} {ascii_name(obj)} in {generic_name(obj.string)}"
    if hasattr(obj, "objects"):
        text += level_suffix(obj, level)
    return text + "\n"


def _bond_text(bond: Any, level: str | None) -> str:
    """``print`` of a bond (``bonds.ss:46``)."""
    category = getattr(bond.bond_category, "name", "")
    direction = getattr(getattr(bond, "direction", None), "name", None)
    word = {"plato-sameness": "same", "plato-successor": "succ", "plato-predecessor": "pred"}.get(
        category, ""
    )
    if category == "plato-sameness":
        arrow = f"={word}="
    elif direction == "plato-left":
        arrow = f"<-{word}-"
    elif direction == "plato-right":
        arrow = f"-{word}->"
    else:
        arrow = ""
    return (
        f"Bond {ascii_name(bond.left_object)} {arrow} {ascii_name(bond.right_object)} "
        f"in {generic_name(bond.string)}{level_suffix(bond, level)}\n"
    )


def _bridge_text(bridge: Any, level: str | None) -> str:
    """``print`` of a horizontal or vertical bridge (``bridges.ss:78``, ``455``)."""
    orientation = "vertical" if getattr(bridge, "bridge_type", "") == "vertical" else "horizontal"
    head = "Spanning " if bridge.is_spanning_bridge else ""
    noun = f"{head}{orientation} bridge" if head else f"{orientation.capitalize()} bridge"
    text = (
        f"{noun} from {ascii_name(bridge.object1)} to {ascii_name(bridge.object2)}"
        f"{level_suffix(bridge, level)}\n"
    )
    for cm in bridge.get_all_concept_mappings():
        text += "     " + concept_mapping_long_name(cm) + "\n"
    return text


def _description_text(desc: Any, level: str | None) -> str:
    """``print`` of a description (``descriptions.ss:33``)."""
    obj = desc.object
    shown = level_suffix(obj) if hasattr(obj, "objects") else ""
    text = (
        f"Description of {ascii_name(obj)}{shown} in {generic_name(obj.string)}: "
        f"{_short(desc.description_type)}:{_node_name(desc.descriptor)}"
    )
    return text + level_suffix(desc, level) + "\n"


def _rule_text(rule: Any, unscored: bool = False) -> str:
    """``print`` of a rule (``rules.ss:119``): its English, then its figures.

    A rule Metacat has made but not yet scored (a translated rule, until the builder's
    ``set-quality-values``) prints every figure as 0; Petacat scores it at translation.
    """
    # Fixed when the rule was made (``rules.ss:98``); every construction site transcribes.
    lines = rule.english_lines or []
    text = "".join(line + "\n" for line in lines)
    if unscored:
        return text + f"(Type={rule.rule_type}, Q=0, RQ=0, Uniformity=0, Abstractness=0, Succinctness=0)\n\n"
    text += (
        f"(Type={rule.rule_type}, Q={display(exact(rule.quality))}, "
        f"RQ={display(exact(_relative_quality(rule)))}, "
        f"Uniformity={display(exact(rule.uniformity))}, "
        f"Abstractness={display(exact(rule.abstractness))}, "
        f"Succinctness={display(exact(rule.succinctness))})\n\n"
    )
    return text


def theme_ascii_name(theme: Any, slipnet: Any) -> str:
    """``ascii-name`` of a bridge theme (``themes.ss:702``): ``LettCtgy:identity``."""
    nodes = getattr(slipnet, "nodes", {}) or {}
    dimension = nodes.get(theme.dimension)
    relation = None
    if theme.relation and theme.relation not in ("diff", "different"):
        relation = nodes.get(theme.relation) or nodes.get("plato-" + theme.relation)
    return f"{_short(dimension) if dimension is not None else theme.dimension}:" + (
        _node_name(relation) if relation is not None else "different"
    )


def _theme_text(theme: Any, slipnet: Any) -> str:
    """``print`` of a bridge theme (``themes.ss:708``)."""
    kind = str(theme.theme_type).replace("_", "-")
    return f"{kind} {theme_ascii_name(theme, slipnet)} theme  ({display(exact(theme.activation))})\n"


def _relative_quality(rule: Any) -> Any:
    return rule.get_relative_quality(rule.workspace)


# ---------------------------------------------------------------------------
# What redisplaying a Trace event says
# ---------------------------------------------------------------------------


def narrate_event_display(log: "VerboseLog", event: Any) -> None:
    """The narration of an event's ``display`` message (``trace.ss``), if it has any.

    Metacat prints these when the user clicks an event in the Trace window and never
    during a run: a clamp and a snag say how much progress was achieved under them
    (``trace.ss:667``, ``1171``), an unjustified answer lists its slippages
    (``trace.ss:427``); an answer prints its slippage log (``trace.ss:452``), and a rule
    event the rule, its clauses and its quality figures (``trace.ss:988``).
    """
    from server.engine import trace as T

    kind = getattr(event, "event_type", None)
    if kind in (T.CLAMP_START, T.CLAMP_END):
        log.say("progress-achieved-by-clamp", exact(getattr(event, "progress_achieved", 0)))
    elif kind == T.SNAG:
        log.say("progress-achieved-by-snag", exact(getattr(event, "progress_achieved", 0)))
    elif kind == T.ANSWER_FOUND:
        # ``display`` of an answer (``trace.ss:427-454``): the unjustified slippages
        # first (only an unjustified answer has any), then ``(print slippage-log)``.
        if getattr(event, "unjustified_slippages", None):
            log.say("unjustified-slippages")
            log.print_object(list(event.unjustified_slippages))
        if getattr(event, "slippage_log", None) is not None:
            log.print_object(event.slippage_log)
    elif kind == T.RULE_BUILT and getattr(event, "structures", None):
        _narrate_rule_display(log, event)


_RULE_DISPLAY_RULE = "-" * 58


def _narrate_rule_display(log: "VerboseLog", event: Any) -> None:
    """The quality block of a rule event's ``display`` (``trace.ss:988-996``)::

        (printf "~n----...~n")  (print rule)  (tell rule 'show)
        (printf "Quality = ~a~n" ...)
        (printf "Relative quality at creation = ~a~n" relative-quality)
        (printf "Relative quality now = ~a" (tell rule 'get-relative-quality))
        (printf "~n----...~n")

    ``rule 'show`` lists the clauses and ends with a blank line (``rules.ss:125-128``).
    """
    rule = event.structures[0]
    text = f"\n{_RULE_DISPLAY_RULE}\n"
    text += print_text(rule, slipnet=log.slipnet)
    text += "".join(rule_clause_text(clause) for clause in rule.clauses) + "\n"
    text += f"Quality = {display(exact(rule.quality))}\n"
    text += f"Relative quality at creation = {display(exact(getattr(event, 'strength', 0)))}\n"
    text += f"Relative quality now = {display(exact(_relative_quality(rule)))}"
    text += f"\n{_RULE_DISPLAY_RULE}\n"
    log.emit(text)


def _format_slipnode(node: Any) -> str:
    """``format-slipnode`` (``rules.ss:2171``): ``<ShortName>``."""
    return f"<{_short(node)}>"


def _format_object_description(od: Any) -> str:
    """``format-object-description`` (``rules.ss:2161``)."""
    head = "string" if od[0] == "string" else _format_slipnode(od[0])
    return f"({head} {_format_slipnode(od[1])} {_format_slipnode(od[2])})"


def rule_clause_text(clause: Any) -> str:
    """``printf-rule-clause`` (``rules.ss:2131-2155``), one clause's lines."""
    if clause.is_verbatim:
        names = " ".join(_node_name(n) for n in clause.verbatim_letters or [])
        return f"VERBATIM ({names})\n"
    descriptions = clause.object_descriptions
    if clause.clause_type == "intrinsic":
        text = f"CHANGE {_format_object_description(descriptions[0])}\n"
        for change in clause.changes:
            target = change.relation if change.relation is not None else change.to_descriptor
            text += f"   ({change.referent} {_format_slipnode(change.dimension)} {_format_slipnode(target)})\n"
        return text
    dims = ", ".join(_format_slipnode(d) for d in clause.dimensions)
    text = f"SWAP {dims} of\n"
    if len(descriptions) == 1:
        return text + f"   subobjects {_format_object_description(descriptions[0])}\n"
    return text + "".join(f"   {_format_object_description(od)}\n" for od in descriptions)


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------


class VerboseLog:
    """The narration of one run: a bounded buffer of lines.

    ``say`` and ``emit`` are only ever called behind an ``if ctx.verbose`` guard, so a run
    with Verbose mode off never reaches this class.  Each line has a sequence number that
    never repeats, which is what lets a client ask for "everything since line N" and learn
    how many lines fell off the front in between.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self.capacity = capacity
        self._lines: deque[tuple[int, str]] = deque(maxlen=capacity)
        self._next = 0
        self._lock = threading.Lock()
        self._messages: dict[str, str] | None = None
        self._provider: Any = None
        #: The run's Slipnet, which ``reveal`` reads node names from.
        self.slipnet: Any = None
        #: Structures this log has seen built.  Metacat's ``break-bond`` leaves a bond's
        #: proposal level at ``%built%``; Petacat's retire resets it, so a bond that is
        #: built, broken and built again would print ``(new)`` here and nothing there.
        self._built: set[tuple[str, int]] = set()

    def bind(self, meta: MetadataProvider | None) -> None:
        """Take the message catalogue from this run's metadata."""
        self._provider = meta
        self._messages = None

    @property
    def messages(self) -> dict[str, str]:
        if self._messages is None:
            from server.engine.metadata import verbose_messages

            self._messages = verbose_messages(self._provider)
        return self._messages

    def mark_built(self, obj: Any) -> None:
        self._built.add((type(obj).__name__, getattr(obj, "id", id(obj))))

    def fresh(self, obj: Any) -> str:
        """The level Metacat would print *obj* at as it is about to be built again:
        ``new`` for an object never built, ``built`` for one that already was."""
        return "built" if (type(obj).__name__, getattr(obj, "id", id(obj))) in self._built else "new"

    def reveal(self, entry: Any) -> list[str]:
        """``reveal`` of a theme-pattern entry (``utilities.ss:936``): a slipnode shows as
        ``<short-name>`` in lower case."""
        nodes = getattr(self.slipnet, "nodes", {}) or {}
        out = []
        for key in ("dimension", "relation"):
            name = entry.get(key) if isinstance(entry, dict) else None
            if key == "relation" and name in (None, "diff", "different"):
                out.append("#f")  # a difference theme has no relation
                continue
            node = nodes.get(name) if isinstance(name, str) else name
            if node is None and isinstance(name, str):
                node = nodes.get("plato-" + name)  # a Themespace relation is spelled bare
            out.append(f"<{_short(node).lower()}>" if node is not None else display(name))
        return out

    def say(self, key: str, *args: Any) -> None:
        """One ``say`` or ``vprintf``: the message *key* with *args* in its ``{}`` places."""
        template = self.messages.get(key)
        if template is None:
            template = f"[{key}]" + " {}" * len(args)
        self.emit(template.format(*[display(a) for a in args]))

    def emit(self, text: str) -> None:
        """Add already-formatted text; each newline-separated piece is a line."""
        if text.endswith("\n"):
            text = text[:-1]
        with self._lock:
            for piece in text.split("\n"):
                self._lines.append((self._next, piece))
                self._next += 1

    def print_object(self, *objects: Any, level: str | None = None) -> None:
        """``(print obj ...)``: each object's own ``print`` text."""
        text = print_text(list(objects), level, self.slipnet)
        if text:
            self.emit(text)

    def banner(self, codelet_type: str) -> None:
        """What every codelet procedure prints first (``syntactic-sugar.ss:250``)."""
        self.emit(f"{DASHES}\nIn {codelet_type} codelet...")

    def capture(self, thunk: Any) -> list[str]:
        """Run *thunk* and return the lines it narrated instead of logging them.

        Some of Metacat's messages come in a different order from Petacat's
        operations (a flipped group is broken inside ``build-bridge`` there, with the
        other breaks here); the narration is held back and ``replay``ed where Metacat
        says it.
        """
        with self._lock:
            mark = self._next
            kept = len(self._lines)
        thunk()
        with self._lock:
            held = [t for n, t in self._lines if n >= mark]
            for _ in range(len(held)):
                self._lines.pop()
            self._next = mark
        return held

    def replay(self, lines: Any) -> None:
        for line in lines:
            self.emit(line)

    def since(self, seq: int = 0) -> dict[str, Any]:
        """The lines numbered *seq* or later, the next number to ask for, and how many
        lines between *seq* and the oldest kept were dropped."""
        with self._lock:
            kept = [(n, t) for n, t in self._lines if n >= seq]
            first = self._lines[0][0] if self._lines else self._next
            return {
                "lines": [t for _, t in kept],
                "next": self._next,
                "first": first,
                "dropped": max(0, first - seq) if seq < first else 0,
                "total": self._next,
            }

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()

    def __len__(self) -> int:
        return len(self._lines)
