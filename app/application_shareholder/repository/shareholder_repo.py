# app/application_shareholder/repository/shareholder_repo.py
from __future__ import annotations

from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from config.database import db
from app.common.models.base import StatusEnum
from app.application_shareholder.models import (
    Shareholder,
    ShareholderEmergencyContact,
    ShareType,
    ShareLedgerEntry,
)


class ShareholderRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # --------------------------
    # Shareholder
    # --------------------------

    def shareholder_code_exists(self, company_id: int, code: str) -> bool:
        stmt = select(Shareholder.id).where(
            Shareholder.company_id == company_id,
            func.lower(Shareholder.code) == func.lower(code),
        )
        return bool(self.s.scalar(stmt))

    def get_shareholder_by_id(self, shareholder_id: int) -> Optional[Shareholder]:
        return self.s.get(Shareholder, shareholder_id)

    def create_shareholder(self, sh: Shareholder) -> Shareholder:
        self.s.add(sh)
        self.s.flush([sh])
        return sh

    def update_shareholder_fields(self, sh: Shareholder, data: dict) -> None:
        for field, value in data.items():
            if hasattr(sh, field) and value is not None:
                setattr(sh, field, value)
        self.s.flush([sh])

    # --------------------------
    # Emergency Contacts
    # --------------------------

    def create_emergency_contacts(
        self,
        shareholder_id: int,
        rows: List[dict],
    ) -> None:
        if not rows:
            return

        objs: List[ShareholderEmergencyContact] = []
        for r in rows:
            objs.append(
                ShareholderEmergencyContact(
                    shareholder_id=shareholder_id,
                    name=r["name"],
                    phone=r["phone"],
                    email=r.get("email"),
                    relationship_to_shareholder=r.get("relationship_to_shareholder"),
                    remarks=r.get("remarks"),
                )
            )
        self.s.add_all(objs)
        self.s.flush(objs)

    def update_emergency_contacts(
        self,
        shareholder_id: int,
        rows: List[dict],
    ) -> None:
        """
        ERP-style: replace all emergency contacts with provided rows.
        """
        self.s.query(ShareholderEmergencyContact).filter(
            ShareholderEmergencyContact.shareholder_id == shareholder_id
        ).delete()
        self.s.flush()
        if rows:
            self.create_emergency_contacts(shareholder_id, rows)

    # --------------------------
    # Share Type
    # --------------------------

    def share_type_code_exists(self, company_id: int, code: str) -> bool:
        stmt = select(ShareType.id).where(
            ShareType.company_id == company_id,
            func.lower(ShareType.code) == func.lower(code),
        )
        return bool(self.s.scalar(stmt))

    def get_share_type_by_id(self, share_type_id: int) -> Optional[ShareType]:
        return self.s.get(ShareType, share_type_id)

    def create_share_type(self, st: ShareType) -> ShareType:
        self.s.add(st)
        self.s.flush([st])
        return st

    def update_share_type_fields(self, st: ShareType, data: dict) -> None:
        for field, value in data.items():
            if hasattr(st, field) and value is not None:
                setattr(st, field, value)
        self.s.flush([st])

    # --------------------------
    # Share Ledger Entries
    # --------------------------

    def create_share_ledger_entry(self, sle: ShareLedgerEntry) -> ShareLedgerEntry:
        self.s.add(sle)
        self.s.flush([sle])
        return sle

    def total_shares_for_shareholder(
        self,
        *,
        company_id: int,
        shareholder_id: int,
        share_type_id: Optional[int] = None,
    ) -> float:
        """
        Returns net quantity of shares for this shareholder:
          sum(quantity) over ShareLedgerEntry.
        Optionally filtered by share_type_id.
        """
        stmt = select(func.coalesce(func.sum(ShareLedgerEntry.quantity), 0)).where(
            ShareLedgerEntry.company_id == company_id,
            ShareLedgerEntry.shareholder_id == shareholder_id,
        )
        if share_type_id:
            stmt = stmt.where(ShareLedgerEntry.share_type_id == share_type_id)

        return float(self.s.scalar(stmt) or 0.0)
