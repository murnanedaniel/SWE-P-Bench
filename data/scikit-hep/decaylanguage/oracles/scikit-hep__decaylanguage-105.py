import graphviz
from decaylanguage.decay.viewer import DecayChainViewer

def test_oracle_001():
    # node_attr passed through to graphviz.Digraph.node_attr
    chain = {"A": [{"fs": ["B", "C"], "bf": 1.0}]}
    dcv = DecayChainViewer(chain, node_attr={"fontsize": "12"})
    assert dcv.graph.node_attr["fontsize"] == "12"

def test_oracle_002():
    # _repr_svg_ should return the graphviz.Digraph object (not an SVG string)
    chain = {"A": [{"fs": ["B", "C"], "bf": 1.0}]}
    dcv = DecayChainViewer(chain)
    rep = dcv._repr_svg_()
    assert isinstance(rep, graphviz.Digraph)

def test_oracle_003():
    # default graph attributes include rankdir="LR" accessible via graph_attr
    chain = {"A": [{"fs": ["B", "C"], "bf": 1.0}]}
    dcv = DecayChainViewer(chain)
    assert dcv.graph.graph_attr.get("rankdir") == "LR"