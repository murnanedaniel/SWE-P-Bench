import pydot
from decaylanguage.decay.viewer import DecayChainViewer


def _make_viewer(chain):
    viewer = DecayChainViewer.__new__(DecayChainViewer)
    viewer._graph = None
    viewer._instantiate_digraph = lambda: pydot.Dot(graph_type="digraph")
    viewer._parsed_decay_chain = {"mother": "M", "fs": chain}
    return viewer


def _node_names(graph):
    return [node.get_name().strip('"') for node in graph.get_nodes()]


def test_oracle_001():
    chain = [
        {
            "bf": 1.0,
            "fs": [
                {"A": [{"bf": 1.0, "fs": ["a1", "a2"]}]},
                {"B": [{"bf": 1.0, "fs": ["b1", "b2"]}]},
            ],
        }
    ]
    viewer = _make_viewer(chain)
    viewer._build_decay_graph()
    names = _node_names(viewer._graph)
    assert len(names) == len(set(names))


def test_oracle_002():
    chain = [
        {
            "bf": 1.0,
            "fs": [
                {"A": [{"bf": 1.0, "fs": ["a1", "a2"]}]},
                {"B": [{"bf": 1.0, "fs": ["b1", "b2"]}]},
            ],
        }
    ]
    viewer = _make_viewer(chain)
    viewer._build_decay_graph()
    graph_str = viewer._graph.to_string()
    assert "dec0:p0" in graph_str
    assert "dec0:p1" in graph_str


def test_oracle_003():
    chain = [
        {
            "bf": 1.0,
            "fs": [
                {"A": [{"bf": 1.0, "fs": ["a1", "a2"]}]},
                "x",
            ],
        },
        {
            "bf": 2.0,
            "fs": [
                {"B": [{"bf": 1.0, "fs": ["b1", "b2"]}]},
                "y",
            ],
        },
    ]
    viewer = _make_viewer(chain)
    viewer._build_decay_graph()
    names = _node_names(viewer._graph)
    assert len(names) == len(set(names))