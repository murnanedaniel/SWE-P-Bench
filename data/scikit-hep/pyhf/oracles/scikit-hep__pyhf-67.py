import pathlib
import pyhf


def _repo_root():
    return pathlib.Path(pyhf.__file__).resolve().parent.parent


def test_oracle_001_travis_default_install_uses_pip_not_conda():
    travis = (_repo_root() / ".travis.yml").read_text()
    assert "conda create -q -n test-environment" not in travis
    assert "wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh" not in travis
    assert "pip install --upgrade pip" in travis
    assert "pip install -U -q -e .[develop]" in travis


def test_oracle_002_travis_benchmark_install_uses_pip_not_conda():
    travis = (_repo_root() / ".travis.yml").read_text()
    assert "stage: benchmark" in travis
    assert "source activate test-environment" not in travis
    assert "conda update -q conda" not in travis
    assert "pip install -U -q -e .[develop]" in travis


def test_oracle_003_setup_requires_newer_pytest_for_develop_extra():
    setup_py = (_repo_root() / "setup.py").read_text()
    assert "'pytest>=3.5.1'" in setup_py
    assert "'pytest>=3.2.0'" not in setup_py