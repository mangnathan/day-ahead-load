from __future__ import annotations

import urllib.request

import pytest

from day_ahead_load import eco2mix


def test_network_is_blocked_during_tests() -> None:
    with pytest.raises(Exception, match="connexion réseau interdite"):
        urllib.request.urlopen(eco2mix.export_url("eco2mix-national-tr"), timeout=5)  # noqa: S310
