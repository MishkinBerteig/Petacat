# Consolidator (v2.0 Base only): one run is one noticing of a symbol.
#
# Posted top-down, with `args['slipnode']`, the node whose activation passed the gate.  The
# node is noticed only if the Workspace holds the symbol (a Letter object whose letter-category
# description is the node); a node raised past the gate by spreading activation alone is primed,
# not noticed, and the codelet fizzles.
#
# Consolidator only proposes.  Each instantiator is posted at the `high` urgency level, as `node-instantiator` is
# (`meta.get_urgency('high')`).  The count of noticings goes to the next turn with a plain
# `propose_ops`.  Each change to this run's Slipnet (a pair's `adjacent` link and its strengthening,
# a symbol's `category` and `instance` links) is proposed for an instantiator, which builds it in
# this run if the evidence still holds and otherwise fizzles (`adjacent-instantiator`,
# `category-instantiator`, `instance-of-instantiator`).  Proposing for a link that already has an
# instantiator waiting only adds to what is held, so the Coderack is not crowded.  A change that no
# instantiator built by the end of the turn is dropped, and only what was built reaches the session.
#
# Parameters, each read only here: `adjacent_link_length` (L) and `adjacent_link_step` (s) for
# the link of a pair of neighbours (the link starts at L and each later noticing multiplies its
# length by r = 1 - s / L, so s is the first step, the steps shrink with the length and the length
# approaches 0 without reaching it); `consolidation_threshold` (in noticings) from which a symbol
# also gets its category and instance links, at `symbol_category_link_length` and
# `symbol_instance_link_length`.
from server.engine.workspace_objects import Letter

node = args.get('slipnode')
letter_category = role('dimension.letter_category')
if not node or not letter_category:
    fizzle()

# Every symbol the Workspace holds, in the Workspace's own order.
letters = [o for s in workspace.aggregate_strings for o in s.objects if isinstance(o, Letter)]
if not any(o.get_descriptor_for(letter_category) is node for o in letters):
    fizzle()

# The noticing.
propose_ops([{'op': 'adjust', 'table': 'slipnet_node_defs', 'key': {'name': node.name},
              'field': 'noticings', 'by': 1}])

# Each built `adjacent` bond between two single symbols, one end of which is this node.  A bond
# with a group at either end, an end with no letter-category description, and a bond of a symbol
# to itself propose nothing.  A pair is noticed from either end, so each end's run counts it.
adjacent = role('bond_category.adjacent')
if adjacent:
    length = meta.get_param('adjacent_link_length')
    step = meta.get_param('adjacent_link_step')
    # Every noticing proposes the link at L / r and a scale by r: the first one leaves the link at
    # (L / r) * r = L, and each later one multiplies it by r.  Factors commute, so the runs of a
    # swarm, which start under one configuration, compose in any order.
    ratio = 1 - step / length
    for s in workspace.aggregate_strings:
        for bond in s.bonds:
            if bond.bond_category is not adjacent:
                continue
            left, right = bond.left_object, bond.right_object
            if not (isinstance(left, Letter) and isinstance(right, Letter)):
                continue
            first = left.get_descriptor_for(letter_category)
            second = right.get_descriptor_for(letter_category)
            if first is None or second is None or first is second:
                continue
            if first is not node and second is not node:
                continue
            propose_ops([
                {'op': 'add_link', 'from': first.name, 'to': second.name, 'type': 'adjacent',
                 'label': adjacent.name, 'fixed': True, 'length': length / ratio},
                {'op': 'scale', 'table': 'slipnet_link_defs',
                 'key': {'from_node': first.name, 'to_node': second.name, 'link_type': 'adjacent',
                         'label_node': adjacent.name},
                 'field': 'link_length', 'factor': ratio},
            ], built_by='adjacent-instantiator', urgency=meta.get_urgency('high'))

# At or past the threshold: the links a letter has to its dimension, if this run's Slipnet lacks them.
if noticings(node) >= meta.get_param('consolidation_threshold'):
    if not any(link.to_node is letter_category for link in links_of(node, 'category')):
        propose_ops([{'op': 'add_link', 'from': node.name, 'to': letter_category.name, 'type': 'category',
                      'fixed': True, 'length': meta.get_param('symbol_category_link_length')}],
                    built_by='category-instantiator', urgency=meta.get_urgency('high'))
    if not any(link.to_node is node for link in links_of(letter_category, 'instance')):
        propose_ops([{'op': 'add_link', 'from': letter_category.name, 'to': node.name, 'type': 'instance',
                      'fixed': True, 'length': meta.get_param('symbol_instance_link_length')}],
                    built_by='instance-of-instantiator', urgency=meta.get_urgency('high'))
