import sys
from pathlib import Path

# Ensure the package in src/ is importable during tests
sys.path.insert(0, str(Path.cwd() / "src"))

from decaylanguage.decay.decay import _expand_decay_modes


def test_oracle_001():
    # Simple mother with two alternative decay modes -> two descriptors expected
    dc = {
        "A": [
            {"bf": 0.5, "fs": ["x", "y"], "model": "PHSP", "model_params": ""},
            {"bf": 0.5, "fs": ["u", "v"], "model": "PHSP", "model_params": ""},
        ]
    }
    descriptors = _expand_decay_modes(dc, top=True, aliases=None)
    assert sorted(descriptors) == sorted(["A -> x y", "A -> u v"])


def test_oracle_002():
    # Nested sub-decay where the sub-particle has two modes -> combinations expected
    dc = {
        "X": [
            {
                "bf": 1.0,
                "fs": [
                    {
                        "D": [
                            {"bf": 0.6, "fs": ["a", "b"], "model": "PHSP", "model_params": ""},
                            {"bf": 0.4, "fs": ["c", "d"], "model": "PHSP", "model_params": ""},
                        ]
                    },
                    "pi0",
                ],
                "model": "VSS",
                "model_params": "",
            }
        ]
    }
    descriptors = _expand_decay_modes(dc, top=True, aliases=None)
    expected = [
        "X -> (D -> a b) pi0",
        "X -> (D -> c d) pi0",
    ]
    assert sorted(descriptors) == sorted(expected)


def test_oracle_003():
    # Alias mapping: key name replaced by alias value in the resulting descriptor
    dc = {
        "MyAntiD0": [
            {"bf": 1.0, "fs": ["K+", "pi-"], "model": "PHSP", "model_params": ""}
        ]
    }
    aliases = {"MyAntiD0": "anti-D0"}
    descriptors = _expand_decay_modes(dc, top=True, aliases=aliases)
    assert descriptors == ["anti-D0 -> K+ pi-"]