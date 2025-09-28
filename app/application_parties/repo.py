# app/party/repo.py

from __future__ import annotations
from typing import Optional, List, Any

from sqlalchemy.orm import Session

from sqlalchemy import select, func, and_


from app.application_parties.parties_models import Party, PartyOrganizationDetail, PartyCommercialPolicy
from config.database import db

from app.application_org.models.company import Branch, Company


class PartyRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    def get_party_by_id(self, party_id: int) -> Optional[Party]:
        """Fetches a Party by its primary key."""
        return self.s.get(Party, party_id)

    def get_party_by_code(self, company_id: int, code: str) -> Optional[Party]:
        """Fetches a Party by its unique code within a company."""
        return self.s.scalar(select(Party).where(
            Party.company_id == company_id,
            func.lower(Party.code) == func.lower(code)
        ))

    def party_code_exists(self, company_id: int, code: str, exclude_party_id: Optional[int] = None) -> bool:
        """Checks for the existence of a party code, optionally excluding a specific party."""
        query = select(Party.id).where(
            Party.company_id == company_id,
            func.lower(Party.code) == func.lower(code)
        )
        if exclude_party_id:
            query = query.where(Party.id != exclude_party_id)
        return bool(self.s.scalar(query))

    def get_cash_party_by_role(self, company_id: int, role: str) -> Optional[Party]:
        """Fetches the single cash party for a given company and role."""
        return self.s.scalar(select(Party).where(
            Party.company_id == company_id,
            Party.is_cash_party.is_(True),
            Party.role == role
        ))

    def get_branch_by_id(self, branch_id: int) -> Optional[Branch]:
        """Fetches a Branch by its primary key ID."""
        return self.s.get(Branch, branch_id)

    # ---- Create Operations ----
    def create_party(self, p: Party) -> Party:
        self.s.add(p)
        self.s.flush()  # to get the party.id
        return p

    def create_organization_details(self, details: PartyOrganizationDetail) -> None:
        self.s.add(details)
        self.s.flush()

    def create_commercial_policy(self, policy: PartyCommercialPolicy) -> None:
        self.s.add(policy)
        self.s.flush()

    # ---- Update & Delete Operations ----
    def update_party(self, p: Party, updates: dict) -> None:
        for key, value in updates.items():
            setattr(p, key, value)
        self.s.flush([p])

    def update_organization_details(self, details: PartyOrganizationDetail, updates: dict) -> None:
        for key, value in updates.items():
            setattr(details, key, value)
        self.s.flush([details])

    def update_commercial_policy(self, policy: PartyCommercialPolicy, updates: dict) -> None:
        for key, value in updates.items():
            setattr(policy, key, value)
        self.s.flush([policy])

    def delete_parties(self, party_ids: List[int]) -> int:
        """Bulk deletes parties by their IDs."""
        # Note: SQLAlchemy's default cascade rules will handle deleting the detail models.
        deleted_count = self.s.query(Party).filter(Party.id.in_(party_ids)).delete(synchronize_session='fetch')
        self.s.flush()
        return deleted_count

    def get_parties_to_delete(self, party_ids: List[int]) -> List[Party]:
        """
        Fetches a list of Party objects for deletion, locking the rows for the transaction.
        This prevents other transactions from modifying them before deletion.
        """
        return self.s.query(Party).filter(Party.id.in_(party_ids)).with_for_update().all()