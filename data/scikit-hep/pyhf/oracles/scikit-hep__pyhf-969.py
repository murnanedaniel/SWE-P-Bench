import re
from pathlib import Path
import pyhf


def test_oracle_001():
    # Ensure docs/conf.py sets the default bibtex style to "unsrt"
    p = Path("docs") / "conf.py"
    assert p.exists(), "docs/conf.py must exist for this test"
    content = p.read_text(encoding="utf-8")
    # Expect an assignment like: bibtex_default_style = "unsrt"
    assert re.search(r'^\s*bibtex_default_style\s*=\s*[\'"]unsrt[\'"]\s*$', content, re.MULTILINE), (
        "Expected bibtex_default_style = 'unsrt' in docs/conf.py"
    )


def test_oracle_002():
    # Ensure the talks bibliography in docs/outreach.rst uses unsrt style
    p = Path("docs") / "outreach.rst"
    assert p.exists(), "docs/outreach.rst must exist for this test"
    content = p.read_text(encoding="utf-8")
    marker = ".. bibliography:: bib/talks.bib"
    idx = content.find(marker)
    assert idx != -1, "talks bibliography marker not found in docs/outreach.rst"
    # Examine the following few lines in that block for the style setting
    block = content[idx : idx + 200]
    assert ":style: unsrt" in block, "Expected ':style: unsrt' for talks bibliography in docs/outreach.rst"


def test_oracle_003():
    # Ensure the use_citations bibliography in docs/citations.rst uses enumerated list and unsrt style
    p = Path("docs") / "citations.rst"
    assert p.exists(), "docs/citations.rst must exist for this test"
    content = p.read_text(encoding="utf-8")
    marker = ".. bibliography:: bib/use_citations.bib"
    idx = content.find(marker)
    assert idx != -1, "use_citations bibliography marker not found in docs/citations.rst"
    # Examine the following few lines in that block for both list and style settings
    block = content[idx : idx + 200]
    assert ":list: enumerated" in block, "Expected ':list: enumerated' for use_citations bibliography in docs/citations.rst"
    assert ":style: unsrt" in block, "Expected ':style: unsrt' for use_citations bibliography in docs/citations.rst"