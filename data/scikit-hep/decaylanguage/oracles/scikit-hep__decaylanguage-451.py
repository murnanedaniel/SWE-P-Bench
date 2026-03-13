import io
import contextlib
from decaylanguage import DecFileParser


DEC_FILE = """Decay B0sig
0.01    MyD*-    MyD_s+   pi0                    PHOTOS  ISGW2;
0.01    MyD*-    MyD_s+   pi+  pi-               PHOTOS  ISGW2;
0.01    MyD*-    MyD_s*+  pi+  pi-               PHOTOS  ISGW2;

0.001  MyD_2*-  MyD_s*+  pi0  pi0               PHOTOS  ISGW2;
0.001  MyD_2*-  MyD_s+   pi+  pi-               PHOTOS  ISGW2;
0.001  MyD_2*-  MyD_s*+  pi+ pi-                PHOTOS  ISGW2;
Enddecay
End
"""


def test_oracle_001():
    # Ensure print_decay_modes prints all decay modes (same BF shouldn't drop any)
    dfp = DecFileParser.from_string(DEC_FILE)
    dfp.parse()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dfp.print_decay_modes("B0sig")
    out = buf.getvalue()
    # There should be 6 printed mode lines (each ending with ;)
    assert out.count(";") == 6


def test_oracle_002():
    # Specifically check that multiple modes sharing the same BF are all present
    dfp = DecFileParser.from_string(DEC_FILE)
    dfp.parse()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dfp.print_decay_modes("B0sig")
    out = buf.getvalue()
    # Two distinct modes with BF 0.01 should both be present
    assert "MyD*- MyD_s+ pi0" in out
    assert "MyD*- MyD_s+ pi+ pi-" in out


def test_oracle_003():
    # Also ensure normalization path does not drop modes with equal BF
    dfp = DecFileParser.from_string(DEC_FILE)
    dfp.parse()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dfp.print_decay_modes("B0sig", normalize=True)
    out = buf.getvalue()
    assert out.count(";") == 6
    # Check one from the lower BF group is present after normalization
    assert "MyD_2*- MyD_s+ pi+ pi-" in out