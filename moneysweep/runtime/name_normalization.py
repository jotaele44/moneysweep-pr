"""Entity-name normalization helpers.

Strips legal suffixes, normalizes '&', collapses whitespace, drops
non-alphanumeric characters. Used to cluster aliases and join entities
across federal, territorial, lobbying, and political-finance datasets.
"""

from __future__ import annotations

import re
import unicodedata

LEGAL_SUFFIXES = frozenset(
    [
        "INC",
        "INCORPORATED",
        "CORP",
        "CORPORATION",
        "CO",
        "COMPANY",
        "LLC",
        "LTD",
        "LP",
        "LLP",
        "PSC",
        "PC",
        "SA",
        "SE",
        "GMBH",
        "PLC",
        "LIMITED",
        "INTL",
        "INTERNATIONAL",
    ]
)

_AMP = re.compile(r"\s*&\s*")
_NON_ALNUM = re.compile(r"[^A-Z0-9 ]+")
_SPACE = re.compile(r"\s+")
# Collapse dotted abbreviations like "S.A.", "L.L.C.", "P.S.C." into a single token.
_DOTTED = re.compile(r"\b(?:[A-Z]\.){2,}")
# Bridge Spanish/English Puerto Rico municipio designators to one canonical
# "MUNICIPIO " prefix so that "Municipio de San Juan", "Municipality of San
# Juan", and "Municipio Autónomo de San Juan" all cluster together. The
# MUNICIPIO marker is kept (rather than collapsing to the bare town) so a
# private entity named after a town does not merge into the government
# municipio. Operates after NFKD accent-folding, so "AUTÓNOMO" has already
# been reduced to "AUTONOMO" before this regex runs.
_MUNICIPIO_PREFIX = re.compile(
    r"^(?:MUNICIPIO(?:\s+AUTONOMO)?\s+DE\s+|MUNICIPALITY\s+OF\s+(?:THE\s+)?)"
)


# Generational/honorific suffix tokens dropped when normalizing *person* names
# so "Pedro Pierluisi", "Pedro Pierluisi Jr." and "PEDRO PIERLUISI III" cluster
# together. Unlike org normalization, person normalization keeps all surnames
# (Puerto Rico naming commonly carries two) and does not strip legal suffixes.
PERSON_SUFFIXES = frozenset(["JR", "SR", "II", "III", "IV", "V"])


def normalize_person_name(name: str | None) -> str:
    """Return a canonical, alphanumeric-uppercase form for a person's name.

    Accent-folds (NFKD), uppercases, removes punctuation, collapses whitespace,
    and drops generational suffixes (JR/SR/II/III/...). All name tokens
    (including a second surname) are preserved. Empty/None -> empty string.
    """
    if not name:
        return ""
    s = str(name).upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _NON_ALNUM.sub(" ", s)
    s = _SPACE.sub(" ", s).strip()
    tokens = [t for t in s.split(" ") if t and t not in PERSON_SUFFIXES]
    return " ".join(tokens)


def normalize_name(name: str | None) -> str:
    """Return a canonical, alphanumeric-uppercase form for clustering.

    Empty or None inputs return an empty string. Pure-punctuation inputs
    also return an empty string. Suffix-only inputs (e.g. "LLC") return an
    empty string.
    """
    if not name:
        return ""
    s = str(name).upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _MUNICIPIO_PREFIX.sub("MUNICIPIO ", s)
    s = _AMP.sub(" AND ", s)
    s = _DOTTED.sub(lambda m: m.group(0).replace(".", ""), s)
    s = _NON_ALNUM.sub(" ", s)
    s = _SPACE.sub(" ", s).strip()
    tokens = [t for t in s.split(" ") if t and t not in LEGAL_SUFFIXES]
    return " ".join(tokens)
