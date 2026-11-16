# Instance-of instantiator (v2.0 Base only): build a letter category's `instance` link to a symbol in this
# run's Slipnet.
#
# Posted only by `consolidator`, with `args['held']`, the link it proposed (the letter category to the
# symbol).  Like a builder in the seed, it checks that what was noticed is still there and builds, or
# fizzles.  The evidence is that the Workspace still holds the symbol (a Letter whose letter-category
# description is the link's `to`) and that this run's Slipnet still lacks the link.  It takes everything
# held for its link and builds it with `apply_ops`.  It draws no random number.
from server.engine.workspace_objects import Letter

ops = take_proposed_ops(args.get('held'))
link = next((op for op in ops if op['op'] == 'add_link'), None)
letter_category = role('dimension.letter_category')
if link is None or not letter_category:
    fizzle()

node = get_node(link['to'])
dimension = get_node(link['from'])
if not node or not dimension:
    fizzle()
letters = [o for s in workspace.aggregate_strings for o in s.objects if isinstance(o, Letter)]
if not any(o.get_descriptor_for(letter_category) is node for o in letters):
    fizzle()
if any(existing.to_node is node for existing in links_of(dimension, link['type'])):
    fizzle()
apply_ops(ops)
