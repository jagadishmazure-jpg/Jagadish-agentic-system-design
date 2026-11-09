"""All domain packs. Portfolio domains first (airport, retail, mortgage, insurance, healthcare)."""

from . import airport, banking, healthcare, insurance, itsm, logistics, mortgage, retail

PACKS = {p.PACK.key: p.PACK for p in (airport, retail, mortgage, insurance, healthcare, banking, itsm, logistics)}


def get_pack(key: str):
    return PACKS[key]
