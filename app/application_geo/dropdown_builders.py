from __future__ import annotations
from typing import Mapping, Any

from sqlalchemy import select, literal
from sqlalchemy.orm import Session

from app.application_org.models.company import City
from app.security.rbac_effective import AffiliationContext  # signature parity with others


def build_cities_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Global cities dropdown.
      • value: City.id
      • label: City.name
      • meta: region

    Optional filters (via params):
      - region: exact match filter (str)
    """
    q = (
        select(
            City.id.label("value"),
            City.name.label("label"),
            City.region.label("region"),
        )
        .order_by(City.name.asc())
    )

    reg = (params or {}).get("region")
    if reg:
        q = q.where(City.region == reg)

    return q
