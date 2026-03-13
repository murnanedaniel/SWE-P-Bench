import os
from pathlib import Path


def test_oracle_001():
    assert not Path(".travis.yml").exists()


def test_oracle_002():
    assert not Path(".appveyor.yml").exists()


def test_oracle_003():
    assert Path("environment.yml").exists()