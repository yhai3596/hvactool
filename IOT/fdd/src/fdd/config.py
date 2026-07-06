"""Configuration assets (FDD-I-012). Externalized so data growth updates configs, not
code, and every value is traceable. Two files under <repo>/config:

- unit_sku_map.yaml : unit -> SKU + data_type (healthy_baseline / fault_injected) routing;
                      sku_rated_kw; h4_proxy_sku. Updated with each data delivery.
- calibration.yaml  : all calibration constants, each tagged source/date/scope.

Local file reads only (no external calls). Cached; call reload() after editing on disk."""
import functools
import pathlib

import yaml

_CONFIG_DIR = pathlib.Path(__file__).resolve().parents[2] / "config"


@functools.lru_cache(maxsize=None)
def _load(name: str) -> dict:
    with open(_CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def reload() -> None:
    """Drop caches so on-disk config edits take effect (data-growth re-calibration)."""
    _load.cache_clear()


# ---------------------------------------------------------------- unit / SKU map

def unit_map() -> dict:
    """{unit: {'sku': str, 'data_type': str}} from unit_sku_map.yaml."""
    return _load("unit_sku_map.yaml")["units"]


def unit_sku(unit: str):
    """SKU for a unit, or None if the unit is not mapped (UNMAPPED, never guessed)."""
    ent = unit_map().get(str(unit))
    return ent["sku"] if ent else None


def unit_data_type(unit: str):
    """'healthy_baseline' | 'fault_injected' | None (unmapped). Unit-level default;
    file-level overrides (FDD-I-017) are resolved by data_type_of()."""
    ent = unit_map().get(str(unit))
    return ent.get("data_type") if ent else None


def data_type_of(unit: str, source_file: str = None):
    """data_type for (unit, source_file): per-file override from the unit's
    file_data_type map (FDD-I-017, keyed by bare file name) else the unit default.
    Lets a healthy unit carry individually fault-injected runs (e.g. unit 31's five
    2023-12-09 undercharge files) without relabeling the whole unit."""
    ent = unit_map().get(str(unit))
    if ent is None:
        return None
    if source_file:
        override = ent.get("file_data_type") or {}
        if source_file in override:
            return override[source_file]
    return ent.get("data_type")


def cooling_ref_quarantine(unit: str) -> list:
    """DK-016 (FDD-I-019-R1): per-unit list of {file, test_condition} whose rows carry a
    cooling-side QUARANTINE FLAG (reference pools / calibration statistics / sh-sc
    baselines must exclude them); rows stay loaded — never deleted."""
    ent = unit_map().get(str(unit))
    return (ent or {}).get("cooling_ref_quarantine") or []


def sku_rated_kw() -> dict:
    return _load("unit_sku_map.yaml")["sku_rated_kw"]


def h4_proxy_sku() -> str:
    return _load("unit_sku_map.yaml")["h4_proxy_sku"]


# ---------------------------------------------------------------- calibration

def cal(dotted: str):
    """Calibration value at a dotted path, e.g. cal('steady.rps_std_max'). Each leaf is
    {value, source, date, scope}; this returns the .value."""
    node = _load("calibration.yaml")
    for key in dotted.split("."):
        node = node[key]
    return node["value"]


def conditions() -> dict:
    """AHRI 210/240 condition points + tolerance from calibration.yaml (FDD-I-015).
    Returns {'tolerance_c': float, 'points': {name: {'ta': float, 'mode': 'heat'/'cool'}}}."""
    c = _load("calibration.yaml")["conditions"]
    return {"tolerance_c": c["tolerance_c"]["value"], "points": c["points"]}
