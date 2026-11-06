"""The Metacat Standard Configuration's vocabulary names, for tests that build structures by hand.

The engine never spells these names: it reads them from the run's vocabulary
(``server/engine/roles.py``, ``meta.vocabulary``), which the configuration's enum tables bind.
A test that builds a bridge, a rule, a theme or a trace event by hand, against the Standard
Configuration (the seed files), spells the name the seed files give.  This module is where
those spellings live, as plain strings, so that a test names the concept (``BRIDGE_TOP``) and
the spelling is in one place.  A test that runs under a renamed vocabulary must not use this
module: it reads the vocabulary instead.
"""

# bridge_types
BRIDGE_TOP = "top"
BRIDGE_BOTTOM = "bottom"
BRIDGE_VERTICAL = "vertical"

# bridge_orientations
ORIENTATION_HORIZONTAL = "horizontal"
ORIENTATION_VERTICAL = "vertical"

# clause_types
CLAUSE_INTRINSIC = "intrinsic"
CLAUSE_EXTRINSIC = "extrinsic"
CLAUSE_VERBATIM = "verbatim"

# rule_types
RULE_TOP = "top"
RULE_BOTTOM = "bottom"

# rule_scopes
SCOPE_SELF = "self"
SCOPE_SUBOBJECTS = "subobjects"

# theme_types
THEME_TOP_BRIDGE = "top_bridge"
THEME_BOTTOM_BRIDGE = "bottom_bridge"
THEME_VERTICAL_BRIDGE = "vertical_bridge"
ALL_THEME_TYPES = [THEME_TOP_BRIDGE, THEME_BOTTOM_BRIDGE, THEME_VERTICAL_BRIDGE]

# theme_relations
RELATION_IDENTITY = "identity"
RELATION_OPPOSITE = "opposite"
RELATION_DIFFERENT = "diff"

# event_types
BOND_BUILT = "bond_built"
BOND_BROKEN = "bond_broken"
GROUP_BUILT = "group_built"
GROUP_BROKEN = "group_broken"
BRIDGE_BUILT = "bridge_built"
BRIDGE_BROKEN = "bridge_broken"
RULE_BUILT = "rule_built"
RULE_BROKEN = "rule_broken"
DESCRIPTION_BUILT = "description_built"
ANSWER_FOUND = "answer_found"
SNAG = "snag"
CLAMP_START = "clamp_start"
CLAMP_END = "clamp_end"
CONCEPT_MAPPING_BUILT = "concept_mapping_built"
CONCEPT_ACTIVATION = "concept_activation"

# proposal_levels
PROPOSED = "proposed"
EVALUATED = "evaluated"
BUILT = "built"

# failure_kinds
FAILURE_SWAP = "swap"
FAILURE_CONFLICT = "conflict"
FAILURE_CHANGE = "change"
