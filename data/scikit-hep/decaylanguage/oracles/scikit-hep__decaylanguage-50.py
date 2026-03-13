import os
import tempfile

from decaylanguage.dec.dec import DecFileParser


def test_oracle_001():
    dec_text = """Decay MyP
1.0 A B PHSP;
Enddecay
End
"""
    parser = DecFileParser.from_string(dec_text)
    parser.parse()
    assert parser.number_of_decays == 1


def test_oracle_002():
    master = """Decay A
1.0 B C PHSP;
Enddecay
End
"""
    user = """Decay X
1.0 A D PHSP;
Enddecay
End
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        master_path = os.path.join(tmpdir, "DECAY.DEC")
        user_path = os.path.join(tmpdir, "my_decay.dec")
        with open(master_path, "w") as f:
            f.write(master)
        with open(user_path, "w") as f:
            f.write(user)

        parser = DecFileParser(master_path, user_path)
        parser.parse()
        assert parser.number_of_decays == 2


def test_oracle_003():
    dec_text = """Decay MyP
1.0 A B PHSP;
Enddecay
End
"""
    parser = DecFileParser.from_string(dec_text)
    assert "decfile(s)=<dec file input as a string>" in repr(parser)