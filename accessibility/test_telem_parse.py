"""Smoke-test KMS line parsing for sticks + lt/rt triggers."""

from makcu_access import Makcu


def parse_kms(line: str) -> dict:
    """Mirror Makcu.read_telem token parsing without a serial port."""
    assert line.startswith("KMS ")
    d = {}
    for tok in line[4:].split():
        k, _, v = tok.partition("=")
        d[k] = int(v, 16) if k == "b" else int(v)
    assert {"lx", "ly", "rx", "ry"} <= d.keys()
    d.setdefault("lt", 0)
    d.setdefault("rt", 0)
    return d


def test_legacy_line_defaults_triggers():
    d = parse_kms("KMS lx=1 ly=2 rx=3 ry=4 b=2000 n=1 ep=82 b0=20 len=20")
    assert d["lt"] == 0 and d["rt"] == 0
    assert d["b"] == 0x2000


def test_new_line_with_triggers():
    d = parse_kms(
        "KMS lx=0 ly=0 rx=0 ry=0 lt=1023 rt=128 b=0000 n=9 ep=82 b0=20 len=20"
    )
    assert d["lt"] == 1023
    assert d["rt"] == 128
    assert Makcu.trigger_pressed(d["lt"])
    assert Makcu.trigger_pressed(d["rt"])
    assert not Makcu.trigger_pressed(10, threshold=64)


if __name__ == "__main__":
    test_legacy_line_defaults_triggers()
    test_new_line_with_triggers()
    print("ok")
