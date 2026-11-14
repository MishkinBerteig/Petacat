# Bottom-up bond scout: choose object, neighbor, propose bond
from server.engine.workspace_objects import Letter

obj = choose_object('intra')
if obj is None:
    fizzle()
if verbose:
    say('chose-object', ascii_name(obj))

neighbor = choose_neighbor(obj)
if neighbor is None:
    if verbose:
        say('chosen-object-no-neighbor')
    fizzle()
if verbose:
    say('chose-neighbor', ascii_name(neighbor))

# Scheme: `choose-bond-facet` (bonds.ss:196, 475-487) -- the facets both objects
# carry a description on, weighted by `description-type-support`
# (workspace-structure-formulas.ss:57-67), which is average(local support,
# activation).  It lives in the builtins now because all three bond scouts call
# it, and the two top-down ones used to hardcode letter-category instead.
bond_facet = choose_bond_facet(obj, neighbor)
if bond_facet is None:
    if verbose:
        say('no-possible-bond-facet')
    fizzle()

obj_desc = obj.get_descriptor_for(bond_facet)
neighbor_desc = neighbor.get_descriptor_for(bond_facet)
if obj_desc is None or neighbor_desc is None:
    fizzle()

# Determine bond category
bond_cat = get_bond_category(obj_desc, neighbor_desc)
if verbose:
    say('chose-descriptors', obj_desc, neighbor_desc)
if bond_cat is None:
    # v2.0 Base: two neighbours that no link relates are still perceived as neighbours.  The
    # bond is of the category the configuration binds to bond_category.adjacent; where nothing
    # is bound the scout fizzles here, as the Standard body does.
    bond_cat = role('bond_category.adjacent')
    if not bond_cat:
        if verbose:
            say('no-bond-between-descriptors')
        fizzle()

# Determine direction
direction = None
sameness = role('bond_category.sameness')
if bond_cat is not sameness:
    if obj.left_string_pos < neighbor.left_string_pos:
        direction = role('direction.right')
    else:
        direction = role('direction.left')


# Scheme: every bond scout consults `incompatible-bond-candidates?` before
# proposing (bonds.ss:209, 254, 313).
from server.engine.bonds import incompatible_bond_candidates
if incompatible_bond_candidates(obj, neighbor, bond_facet, bond_cat):
    if verbose:
        say('incompatible-bond-candidates')
    fizzle()

propose_bond(obj, neighbor, bond_cat, bond_facet, obj_desc, neighbor_desc, direction)
