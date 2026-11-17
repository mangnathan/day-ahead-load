from __future__ import annotations

from datetime import date

from day_ahead_load import calendar_features as cal


def test_bridges_follow_the_written_rule() -> None:
    days = cal.daily_calendar(date(2024, 5, 6), date(2025, 11, 14))
    assert days.loc[date(2024, 5, 10), "pont"]  # vendredi après l'Ascension (jeudi 09/05)
    assert days.loc[date(2025, 11, 10), "pont"]  # lundi avant le mardi 11/11
    assert not days.loc[date(2024, 12, 24), "pont"]  # Noël un mercredi : pas de pont
    assert not days.loc[date(2024, 5, 11), "pont"]  # samedi
    bridges = [d for d, flag in days["pont"].items() if flag]
    assert bridges == [
        date(2024, 5, 10),  # Ascension, jeudi
        date(2024, 8, 16),  # Assomption, jeudi
        date(2025, 5, 2),  # 1er mai, jeudi
        date(2025, 5, 9),  # 8 mai, jeudi
        date(2025, 5, 30),  # Ascension, jeudi
        date(2025, 11, 10),  # 11 novembre, mardi
    ]


def test_pentecost_monday_has_its_own_flag() -> None:
    days = cal.daily_calendar(date(2024, 5, 20), date(2024, 5, 20))
    row = days.loc[date(2024, 5, 20)]
    assert row["lundi_pentecote"]
    assert not row["ferie"]


def test_christmas_period_and_alsace_limit() -> None:
    days = cal.daily_calendar(date(2024, 12, 20), date(2025, 1, 3))
    noel = [d for d, flag in days["noel"].items() if flag]
    assert noel[0] == date(2024, 12, 24)
    assert noel[-1] == date(2025, 1, 1)
    assert len(noel) == 9
    assert days.loc[date(2024, 12, 25), "ferie"]
    assert not days.loc[date(2024, 12, 26), "ferie"]  # férié en Alsace-Moselle seulement
