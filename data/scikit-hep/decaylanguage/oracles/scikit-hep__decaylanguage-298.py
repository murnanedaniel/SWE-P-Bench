import importlib
import importlib.resources as resources
import decaylanguage.modeling.ampgen2goofit as ampmod
import decaylanguage.__main__ as mainmod


def test_oracle_001():
    # The patched code introduces ampgen2goofitpy in the ampgen2goofit module.
    # Before the fix this attribute does not exist and the test must fail.
    assert hasattr(ampmod, "ampgen2goofitpy") and callable(getattr(ampmod, "ampgen2goofitpy"))


def test_oracle_002():
    # The patched __main__ handles the "goofitpy" generator and calls ampgen2goofitpy.
    # We inject a sentinel function and assert it is called by DecayLanguageDecay.main.
    called = {"hit": False}

    def fake_ampgen2goofitpy(filename):
        called["hit"] = True

    # Ensure our fake is present in the module namespace (pre-patch the code will not call it).
    mainmod.ampgen2goofitpy = fake_ampgen2goofitpy

    app = mainmod.DecayLanguageDecay()
    # Simulate selecting the new generator option
    app.generator = "goofitpy"
    # Call main; patched code should call our fake and set the flag.
    app.main("dummy_filename")
    assert called["hit"] is True


def test_oracle_003():
    # The grammar file ampgen.lark was changed: the 'fix' rule now maps SIGNED_NUMBER -> checkfixed.
    # Before the patch the rule used explicit "0" and "2" alternatives.
    text = resources.files("decaylanguage.data").joinpath("ampgen.lark").read_text(encoding="utf8")
    assert "fix : SIGNED_NUMBER -> checkfixed" in text