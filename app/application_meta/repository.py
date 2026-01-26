from __future__ import annotations
from typing import List, Optional, Dict

from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from config.database import db
from app.application_meta.models import Doctype, DocField, DocLink


class MetaRepository:
    def __init__(self, session: Optional[Session] = None) -> None:
        self.session = session or db.session

    # --------- doctypes ---------
    def get_doctype_by_name(self, name: str) -> Optional[Doctype]:
        stmt = select(Doctype).where(Doctype.name == name)
        return self.session.execute(stmt).scalar_one_or_none()

    # --------- fields (with company overrides) ---------
    def get_effective_fields(
        self,
        *,
        doctype_id: int,
        company_id: Optional[int] = None,
    ) -> List[DocField]:
        """
        Returns merged fields:
          - base rows (company_id IS NULL)
          - overrides for specific company_id (if any) by same fieldname
        """
        base_stmt = (
            select(DocField)
            .where(
                and_(
                    DocField.doctype_id == doctype_id,
                    DocField.company_id.is_(None),
                )
            )
            .order_by(DocField.idx)
        )
        base_fields = self.session.execute(base_stmt).scalars().all()
        base_by_name: Dict[str, DocField] = {f.fieldname: f for f in base_fields}

        if company_id:
            override_stmt = (
                select(DocField)
                .where(
                    and_(
                        DocField.doctype_id == doctype_id,
                        DocField.company_id == company_id,
                    )
                )
                .order_by(DocField.idx)
            )
            overrides = self.session.execute(override_stmt).scalars().all()
            for f in overrides:
                base_by_name[f.fieldname] = f  # override or add

        # return sorted by idx from final objects
        merged = list(base_by_name.values())
        merged.sort(key=lambda f: f.idx)
        return merged

    # --------- permissions ---------


    # --------- links (connections) ---------
    def get_links(self, *, parent_doctype_name: str) -> List[DocLink]:
        stmt = select(DocLink).where(DocLink.parent_doctype == parent_doctype_name)
        return self.session.execute(stmt).scalars().all()


meta_repository = MetaRepository()
