from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import frozen
from day_ahead_load import modelling as md
from day_ahead_load import table as tb


def synthetic(first: date, days: int) -> pd.DataFrame:
    """Table fictive, de l'entraînement jusqu'au test, avec une cible et des résidus."""
    rng = np.random.default_rng(1)
    out = []
    for k in range(days):
        day = first + timedelta(days=k)
        period = tb.period(day)
        for slot in range(0, 48, 4):
            row = {name: float(rng.normal()) for name in md.FEATURES}
            row.update(
                {
                    "jour": day,
                    "periode": period,
                    "demi_heure": slot,
                    "jour_semaine": day.weekday(),
                    "mois": day.month,
                    tb.TARGET: 50_000.0 + 100.0 * row["temperature_2m"],
                    "residu": float(rng.normal(0, 500)),
                }
            )
            out.append(row)
    return pd.DataFrame(out)


def poison_test_period(table: pd.DataFrame) -> pd.DataFrame:
    out = table.copy()
    in_test = np.asarray(out["periode"] == "test")
    out.loc[in_test, tb.TARGET] = 1e9
    out.loc[in_test, "residu"] = 1e9
    return out


@pytest.fixture(scope="module")
def table() -> pd.DataFrame:
    # Du 01/08/2025 au 31/10/2025 : la fin de la validation et le début du test.
    return synthetic(date(2025, 8, 1), 92)


def test_frozen_training_rows_stop_at_the_end_of_validation(table: pd.DataFrame) -> None:
    rows = frozen.training_rows(table)
    assert max(rows["jour"]) == date(2025, 8, 31)
    with pytest.raises(ValueError, match="validation"):
        frozen.fit_model(table[table[tb.TARGET].notna()])


def test_poisoning_the_test_period_leaves_model_offsets_and_q_identical_byte_for_byte(
    table: pd.DataFrame,
) -> None:
    poisoned = poison_test_period(table)
    model = frozen.fit_model(frozen.training_rows(table))
    model_poisoned = frozen.fit_model(frozen.training_rows(poisoned))
    assert frozen.sha256(model) == frozen.sha256(model_poisoned)
    offsets = frozen.offsets_json(frozen.offsets(table["residu"], table))
    offsets_poisoned = frozen.offsets_json(frozen.offsets(poisoned["residu"], poisoned))
    assert offsets.encode() == offsets_poisoned.encode()
    assert frozen.PURCHASE_Q == 0.4616


def test_offsets_are_per_half_hour_and_include_the_purchase_level(table: pd.DataFrame) -> None:
    out = frozen.offsets(table["residu"], table)
    assert list(out.columns) == ["0.025", "0.1", "0.5", "0.9", "0.975", "0.4616"]
    assert set(out.index) == set(range(0, 48, 4))
    assert (out["0.025"] <= out["0.975"]).all()
