import inspect
from particle.particle.particle import Particle

def test_oracle_001():
    src = inspect.getsource(Particle._from_group_dict_list)
    fam_pat = "if mat['family']:\n            fullname += '({mat[family]})'.format(mat=mat)"
    state_pat = "if mat['state']:\n            fullname += '({mat[state]})'.format(mat=mat)"
    star_pat = "if mat['star']:\n            fullname += '*'"
    i_fam = src.find(fam_pat)
    i_state = src.find(state_pat)
    i_star = src.find(star_pat)
    assert i_fam != -1 and i_state != -1 and i_star != -1
    # Ensure star is appended after family and state (fixed behaviour)
    assert i_fam < i_state < i_star

def test_oracle_002():
    src = inspect.getsource(Particle._from_group_dict_list)
    star_pat = "if mat['star']:\n            fullname += '*'"
    # Star append should appear exactly once and after family/state
    assert src.count(star_pat) == 1
    fam_index = src.find("if mat['family']:\n            fullname += '({mat[family]})'.format(mat=mat)")
    state_index = src.find("if mat['state']:\n            fullname += '({mat[state]})'.format(mat=mat)")
    star_index = src.find(star_pat)
    assert fam_index != -1 and state_index != -1
    assert star_index > fam_index and star_index > state_index

def test_oracle_003():
    src = inspect.getsource(Particle._from_group_dict_list)
    # In the buggy version the star was inserted before the family/state blocks.
    # Ensure that sequence ("star then family") does not occur.
    bad_sequence = "if mat['star']:\n            fullname += '*'\n\n        if mat['family']"
    assert bad_sequence not in src