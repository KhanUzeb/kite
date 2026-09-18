from clamp import clamp


def test_clamp_inside_range() -> None:
    assert clamp(5, 0, 10) == 5


def test_clamp_below() -> None:
    assert clamp(-3, 0, 10) == 0


def test_clamp_above() -> None:
    assert clamp(14, 0, 10) == 10
