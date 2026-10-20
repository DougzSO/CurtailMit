import pytest

from curtailmit.pld import fetch_pld, PldDisabledError


def test_fetch_pld_raises_when_disabled():
    with pytest.raises(PldDisabledError):
        fetch_pld(enabled=False)


def test_fetch_pld_raises_not_implemented_when_enabled():
    with pytest.raises(NotImplementedError):
        fetch_pld(enabled=True)