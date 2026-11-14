"""Garde-fou commun à tous les tests : aucune connexion réseau.

Les tests ne tournent que sur des données fictives. Une connexion vers ODRÉ, Open-Meteo ou
RTE depuis un test serait une erreur : elle dépendrait d'un service extérieur et, en CI,
consommerait des quotas gratuits.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest


class NetworkBlockedError(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise NetworkBlockedError("connexion réseau interdite pendant les tests")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield
