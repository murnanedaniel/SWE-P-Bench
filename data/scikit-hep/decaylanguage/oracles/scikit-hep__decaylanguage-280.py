import inspect
from decaylanguage.dec import dec as decmod
from decaylanguage.dec.dec import load_grammar


def test_oracle_001():
    # The default value of the `lexer` parameter must be 'auto' to adapt to Lark 1.x.
    sig = inspect.signature(load_grammar)
    assert "lexer" in sig.parameters, "load_grammar has no 'lexer' parameter"
    default = sig.parameters["lexer"].default
    assert default == "auto", f"Expected default lexer 'auto', got {default!r}"


def test_oracle_002():
    # The function docstring should state that the default is 'auto'.
    doc = load_grammar.__doc__ or ""
    assert "default='auto'" in doc or 'default="auto"' in doc, "Docstring must mention default='auto'"


def test_oracle_003():
    # The module source should contain the lexer parameter default set to "auto" in the function signature.
    src = inspect.getsource(decmod)
    ok = ('lexer: str = "auto"' in src) or ("lexer: str = 'auto'" in src) or ('lexer: str = "auto",' in src) or ("lexer: str = 'auto'," in src)
    assert ok, "Module source must set lexer default to 'auto' in the load_grammar signature"