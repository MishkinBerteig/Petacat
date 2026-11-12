# Symbol builder (v2.0 Base only): make the node for a symbol seen for the first time.
#
# The node is connected to nothing.  Its glyph and short name are the character, which is all
# that perceiving the symbol needs: sameness bonds, groups of the symbol and answers that keep
# the symbol all work.  Every relation to another symbol is learned later, or never.  This
# codelet proposes no trigger and no link.
from server.engine.workspace_objects import Letter

obj = args.get('obj')
ch = args.get('glyph')
if obj is None or ch is None:
    fizzle()

# The premises of the scout: the object is still in its string and still undescribed.
if obj.string is None or obj not in obj.string.objects:
    fizzle()
letter_category = role('dimension.letter_category')
if not letter_category or obj.get_descriptor_for(letter_category) is not None:
    fizzle()

node = letter_node(ch)
if not node:
    # One op, one row, named from the code point, so two runs that meet the same symbol
    # produce the same row and the second is a duplicate the change API skips.
    apply_ops([{
        'op': 'add_node',
        'name': 'plato-cp-%04x' % ord(ch),
        'fields': {
            'short_name': ch,
            'glyph': ch,
            'plain_name': ch,
            'article_an': False,
            'conceptual_depth': meta.get_param('new_node_conceptual_depth'),
            'description': 'The symbol U+%04X, perceived in a Training Mode Session.' % ord(ch),
        },
    }])
    node = letter_node(ch)  # apply_ops rebuilt this run's alphabet
    if not node:
        fizzle()

obj.letter_category = node
propose_description(obj, letter_category, node)
