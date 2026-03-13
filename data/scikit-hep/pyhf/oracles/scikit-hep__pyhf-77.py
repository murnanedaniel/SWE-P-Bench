import pyhf

def _read_setup_py():
    with open("setup.py", "r", encoding="utf-8") as fh:
        return fh.read()

def test_oracle_001():
    # The patch adds the pytest-benchmark extra to setup.py install requirements.
    content = _read_setup_py()
    assert "pytest-benchmark[histogram]" in content

def test_oracle_002():
    # Ensure the specific extra form appears (not just 'pytest-benchmark' alone).
    content = _read_setup_py()
    assert "pytest-benchmark[histogram]" in content and "[" in "pytest-benchmark[histogram]"

def test_oracle_003():
    # Make sure the new requirement appears in the install_requires block of setup.py
    content = _read_setup_py()
    # basic sanity: setup.py should mention install_requires and include the benchmark extra
    assert "install_requires" in content and "pytest-benchmark[histogram]" in content