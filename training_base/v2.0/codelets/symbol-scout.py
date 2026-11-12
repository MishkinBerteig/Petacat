# Symbol scout (v2.0 Base only): notice a symbol that has no letter-category description.
#
# Written in the idiom of bottom-up-description-scout: the object is chosen by *average*
# salience, and what is found is proposed as an ordinary description, so the ordinary
# description-evaluator and description-builder do the rest and the symbols of a string are
# perceived one object at a time.
from server.engine.workspace_objects import Letter

obj = choose_object('average')
if obj is None or not isinstance(obj, Letter):
    fizzle()

# Perceived means: the object carries a letter-category description (the test that
# `num_unperceived_symbols` counts).  A built description is enough to stop.
letter_category = role('dimension.letter_category')
if not letter_category or obj.get_descriptor_for(letter_category) is not None:
    fizzle()

# The raw character.  A Letter built from a glyph with no node has no letter category, but
# the character is still in the string.
ch = obj.string.text[obj.left_string_pos]

node = letter_node(ch)
if node:
    # The symbol has a node (made for another object of this run, or kept from an earlier
    # run of the session).  Perceiving this object needs no new structure: bind the letter
    # to the node and propose the ordinary description.
    obj.letter_category = node
    propose_description(obj, letter_category, node)
else:
    # No node.  Making one changes the configuration, so it is posted as its own codelet,
    # which checks its premises again before it acts (two scouts can reach this point).
    post_codelet('symbol-builder', meta.get_urgency('high'), obj=obj, glyph=ch)
