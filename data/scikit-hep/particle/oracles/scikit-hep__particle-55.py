import importlib.resources as resources

def test_oracle_001():
    # Attempt to read the packaged CSV via importlib.resources.read_text.
    # Before the fix the file is not included and this will raise FileNotFoundError (test fails).
    # After the fix the file is present and we assert its contents are non-empty and look like CSV.
    text = resources.read_text('particle.data', 'particle2018.csv')
    assert text, "particle2018.csv should be non-empty"
    assert ',' in text.splitlines()[0], "Expected CSV header line"

def test_oracle_002():
    # Use open_text to trigger the same resource access path.
    with resources.open_text('particle.data', 'particle2018.csv') as f:
        content = f.read()
    assert len(content) > 0
    # Expect a header column name typical for particle CSVs
    assert 'pdg' in content.lower() or 'name' in content.lower()

def test_oracle_003():
    # Use the modern files API to access the resource file.
    file_text = resources.files('particle.data').joinpath('particle2018.csv').read_text(encoding='utf-8')
    assert file_text.strip() != ""
    # Basic sanity: should contain at least one comma (CSV)
    assert ',' in file_text.splitlines()[0]