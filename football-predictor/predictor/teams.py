"""Map bookmaker team names (SportyBet, etc.) to football-data.co.uk names."""
from __future__ import annotations

import difflib
import re

ALIASES = {
    # England
    "manchester united": "Man United", "man utd": "Man United",
    "manchester city": "Man City", "nottingham forest": "Nott'm Forest",
    "nottingham": "Nott'm Forest", "wolverhampton": "Wolves",
    "wolverhampton wanderers": "Wolves", "tottenham hotspur": "Tottenham",
    "spurs": "Tottenham", "newcastle united": "Newcastle",
    "west ham united": "West Ham", "brighton & hove albion": "Brighton",
    "brighton and hove albion": "Brighton", "afc bournemouth": "Bournemouth",
    "leeds united": "Leeds", "sheffield united": "Sheffield United",
    "leicester city": "Leicester", "ipswich town": "Ipswich",
    "hull city": "Hull", "coventry city": "Coventry", "norwich city": "Norwich", "luton town": "Luton",
    "cardiff city": "Cardiff", "swansea city": "Swansea", "stoke city": "Stoke",
    # Spain
    "atletico madrid": "Ath Madrid", "atletico de madrid": "Ath Madrid",
    "athletic bilbao": "Ath Bilbao", "athletic club": "Ath Bilbao",
    "real betis": "Betis", "real sociedad": "Sociedad", "celta vigo": "Celta",
    "rayo vallecano": "Vallecano", "deportivo alaves": "Alaves",
    "espanyol barcelona": "Espanol", "espanyol": "Espanol", "fc barcelona": "Barcelona",
    "real oviedo": "Oviedo", "real valladolid": "Valladolid",
    # Italy
    "inter milan": "Inter", "internazionale": "Inter", "ac milan": "Milan",
    "as roma": "Roma", "ss lazio": "Lazio", "hellas verona": "Verona",
    "ssc napoli": "Napoli", "juventus turin": "Juventus",
    # Germany
    "bayern munich": "Bayern Munich", "fc bayern munchen": "Bayern Munich",
    "bayern munchen": "Bayern Munich", "borussia dortmund": "Dortmund",
    "borussia monchengladbach": "M'gladbach", "monchengladbach": "M'gladbach",
    "bayer leverkusen": "Leverkusen", "eintracht frankfurt": "Ein Frankfurt",
    "rb leipzig": "RB Leipzig", "vfb stuttgart": "Stuttgart",
    "vfl wolfsburg": "Wolfsburg", "sc freiburg": "Freiburg",
    "tsg hoffenheim": "Hoffenheim", "1899 hoffenheim": "Hoffenheim",
    "fc koln": "FC Koln", "1. fc koln": "FC Koln", "cologne": "FC Koln",
    "1. fc union berlin": "Union Berlin", "fsv mainz 05": "Mainz", "mainz 05": "Mainz",
    "1. fsv mainz 05": "Mainz", "fc augsburg": "Augsburg", "hamburger sv": "Hamburg",
    "fc st. pauli": "St Pauli", "st. pauli": "St Pauli", "1. fc heidenheim": "Heidenheim",
    # France
    "paris saint-germain": "Paris SG", "paris saint germain": "Paris SG", "psg": "Paris SG",
    "olympique marseille": "Marseille", "olympique de marseille": "Marseille",
    "olympique lyonnais": "Lyon", "olympique lyon": "Lyon", "as monaco": "Monaco",
    "losc lille": "Lille", "stade rennais": "Rennes", "rc lens": "Lens",
    "ogc nice": "Nice", "stade brestois": "Brest", "rc strasbourg": "Strasbourg",
    "saint-etienne": "St Etienne", "as saint-etienne": "St Etienne",
    "paris fc": "Paris FC",
    # Understat spellings
    "west bromwich albion": "West Brom", "borussia m.gladbach": "M'gladbach",
    "rasenballsport leipzig": "RB Leipzig", "fc cologne": "FC Koln", "hertha berlin": "Hertha",
    "arminia bielefeld": "Bielefeld", "greuther fuerth": "Greuther Furth",
    "fortuna duesseldorf": "Fortuna Dusseldorf", "parma calcio 1913": "Parma", "spal 2013": "Spal",
    "deportivo la coruna": "La Coruna", "sd huesca": "Huesca", "clermont foot": "Clermont",
    "racing santander": "Santander", "sporting gijon": "Sp Gijon",
    # SportyBet spellings the word match below can't place
    "rc deportivo de a coruna": "La Coruna", "como 1907": "Como", "borussia m'gladbach": "M'gladbach",
    "estac troyes": "Troyes", "queens park rangers": "QPR", "sporting": "Sp Lisbon",
    "sporting cp": "Sp Lisbon", "sporting lisbon": "Sp Lisbon", "union gilloise": "St. Gilloise",
    "union saint-gilloise": "St. Gilloise", "amed sportif faaliyetler": "Amedspor", "goztepe izmir": "Goztep",
    "goztepe": "Goztep", "istanbul bb": "Buyuksehyr", "istanbul basaksehir": "Buyuksehyr",
    "heart of midlothian fc": "Hearts", "heart of midlothian": "Hearts", "1 fc nuremberg": "Nurnberg",
    "1. fc nurnberg": "Nurnberg", "nuremberg": "Nurnberg", "rc celta fortuna": "Celta B",
    "celta fortuna": "Celta B", "panaitolikos agrinio": "Panetolikos", "panaitolikos": "Panetolikos",
}
GENERIC_WORDS = {"fc", "afc", "cf", "sc", "ac", "as", "ssc", "calcio", "club"}


def _words(name: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", _clean(name))) - GENERIC_WORDS - {""}


def _clean(name: str) -> str:
    name = name.lower().strip()
    for a, b in (("ü", "u"), ("ö", "o"), ("é", "e"), ("è", "e"), ("á", "a"), ("í", "i"), ("ó", "o"),
                 ("´", "'"), ("’", "'"), ("`", "'")):
        name = name.replace(a, b)
    return re.sub(r"\s+", " ", name)


def resolve(name: str, known: list[str]) -> str:
    """Return the matching known team name, or raise KeyError with suggestions."""
    if name in known:
        return name
    clean = _clean(name)
    lookup = {_clean(k): k for k in known}
    if clean in lookup:
        return lookup[clean]
    alias = ALIASES.get(clean)
    if alias in known:
        return alias
    stripped = re.sub(r"\b(fc|afc|cf|sc|ac|as|ssc|calcio|club)\b", "", clean).strip()
    if stripped in lookup:
        return lookup[stripped]
    close = difflib.get_close_matches(stripped, list(lookup), n=1, cutoff=0.75)
    if close:
        return lookup[close[0]]
    # Last resort: exactly one known team whose every word appears in the name,
    # e.g. "Blackburn Rovers" -> "Blackburn", "Besiktas Istanbul" -> "Besiktas".
    words = _words(name)
    within = [k for k in known if _words(k) and _words(k) <= words]
    if len(within) == 1:
        return within[0]
    hint = difflib.get_close_matches(stripped, list(lookup), n=3, cutoff=0.4)
    raise KeyError(f"Unknown team {name!r}. Closest: {[lookup[h] for h in hint]}. "
                   f"Add it to ALIASES in predictor/teams.py.")
