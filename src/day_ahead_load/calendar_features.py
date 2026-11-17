"""Variables de calendrier, par jour (heure de Paris).

Jours fériés : bibliothèque `holidays` (licence MIT), qui les calcule sans appel réseau ni
fichier à tenir à jour ; sa version est figée par `uv.lock`, donc la liste est reproductible.
Le jeu de données de calendrier.api.gouv.fr aurait demandé un téléchargement, un cache et une
vérification de licence pour la même information.

Règles écrites avant toute mesure :

- `ferie` : jours fériés de métropole hors Alsace-Moselle, sauf le lundi de Pentecôte, qui a
  son propre indicateur : il est férié en droit, mais il est la journée de solidarité depuis
  2005 et une partie des entreprises travaille. Limite : le Vendredi saint et le 26/12, fériés
  en Alsace-Moselle seulement, ne sont pas marqués ;
- `pont` : jour ouvré (lundi à vendredi, non férié) coincé entre un jour férié et le
  week-end, c'est-à-dire un lundi dont le mardi est férié, ou un vendredi dont le jeudi est
  férié. Le lundi de Pentecôte compte comme férié pour cette règle, mais tombant un lundi, il
  ne crée jamais de pont. Les mercredis fériés ne créent pas de pont ;
- `noel` : du 24/12 au 01/01 inclus, chaque année. La semaine entre Noël et le Nouvel An se
  comporte très différemment des autres et ne demande aucune source.
"""

from __future__ import annotations

from datetime import date, timedelta

import holidays
import pandas as pd

PENTECOST_MONDAY = "Lundi de Pentecôte"


def public_holidays(first: date, last: date) -> dict[date, str]:
    """Jours fériés de métropole (hors Alsace-Moselle) entre deux dates incluses."""
    calendar = holidays.country_holidays("FR", years=range(first.year, last.year + 1))
    return {d: str(name) for d, name in calendar.items() if first <= d <= last}


def is_christmas_period(day: date) -> bool:
    return (day.month == 12 and day.day >= 24) or (day.month == 1 and day.day == 1)


def daily_calendar(first: date, last: date) -> pd.DataFrame:
    """Une ligne par jour : jour de la semaine (0 = lundi), mois, férié, Pentecôte, pont, Noël."""
    # Un jour de marge de chaque côté : le pont d'un lundi dépend du mardi qui suit.
    holidays_by_day = public_holidays(first - timedelta(days=1), last + timedelta(days=1))
    days = pd.date_range(first, last, freq="D")
    rows = []
    for stamp in days:
        day = stamp.date()
        name = holidays_by_day.get(day)
        weekday = day.weekday()
        off = name is not None or weekday >= 5
        bridge = not off and (
            (weekday == 0 and (day + timedelta(days=1)) in holidays_by_day)
            or (weekday == 4 and (day - timedelta(days=1)) in holidays_by_day)
        )
        rows.append(
            {
                "jour": day,
                "jour_semaine": weekday,
                "mois": day.month,
                "ferie": name is not None and name != PENTECOST_MONDAY,
                "lundi_pentecote": name == PENTECOST_MONDAY,
                "pont": bridge,
                "noel": is_christmas_period(day),
            }
        )
    return pd.DataFrame(rows).set_index("jour")
