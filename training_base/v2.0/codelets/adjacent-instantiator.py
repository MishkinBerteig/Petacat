# Adjacent instantiator (v2.0 Base only): build a pair's `adjacent` link in this run's Slipnet.
#
# Posted only by `consolidator`, with `args['held']`, the link it proposed (from, to, type, label).  Like a
# builder in the seed, it checks that what was noticed is still there and builds, or fizzles.  Here the
# evidence is a built `adjacent` bond in the Workspace between two single symbols whose letter-category
# descriptions are the link's `from` and `to`, `from` on the left (reading order, as `consolidator` reads
# it).  The codelet takes everything held for its link (the first noticing's `add_link` at L / r and, for
# each noticing, a `scale` by r, composed into one) and builds it with `apply_ops`: from then on the run's
# Slipnet has the link at its new length, and it is recorded for the session.  It draws no random number.
#
# One more rule, the user's: an `adjacent` link is built only between two symbols that no other link joins.  If this
# run's Slipnet has a link of any other type (labelled or not, in either direction) between the link's `from` and `to`,
# the codelet fizzles and what it took is dropped, whether the build would have created the link or strengthened it.
# A pair joined only by its own `adjacent` link still builds and strengthens.
from server.engine.workspace_objects import Letter

ops = take_proposed_ops(args.get('held'))
link = next((op for op in ops if op['op'] == 'add_link'), None)
letter_category = role('dimension.letter_category')
adjacent = role('bond_category.adjacent')
if link is None or not letter_category or not adjacent:
    fizzle()

# The pairs of names of the built `adjacent` bonds between two single symbols, left to right.
pairs = []
for s in workspace.aggregate_strings:
    for bond in s.bonds:
        if bond.bond_category is not adjacent:
            continue
        left, right = bond.left_object, bond.right_object
        if not (isinstance(left, Letter) and isinstance(right, Letter)):
            continue
        first = left.get_descriptor_for(letter_category)
        second = right.get_descriptor_for(letter_category)
        if first is not None and second is not None:
            pairs.append((first.name, second.name))

if (link['from'], link['to']) not in pairs:
    # The bond is gone (broken since it was noticed), or never joined these two symbols.  What was
    # taken is dropped.
    fizzle()

first, second = get_node(link['from']), get_node(link['to'])
for node, other in ((first, second), (second, first)):
    if any(other_link.to_node is other and other_link.link_type != link['type'] for other_link in node.outgoing_links):
        fizzle()
apply_ops(ops)
