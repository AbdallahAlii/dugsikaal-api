
from __future__ import annotations
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, noload
from sqlalchemy.exc import IntegrityError

from config.database import db
from app.application_org.models.code_counter_model import CodeType, CodeCounter


def get_code_type_by_prefix(prefix: str, *, session: Optional[Session] = None) -> Optional[CodeType]:
    s = session or db.session
    if not prefix:
        return None
    stmt = select(CodeType).where(CodeType.prefix == prefix)
    return s.scalar(stmt)


# def get_or_create_counter_row(
#     *,
#     code_type_id: int,
#     company_id: Optional[int],
#     branch_id: Optional[int],
#     period_key: Optional[str],
#     session: Optional[Session] = None,
# ) -> CodeCounter:
#     """
#     Return a locked row for (type, company, branch, period). If missing, create it
#     atomically under a SAVEPOINT; never roll back the whole transaction.
#     """
#     s = session or db.session
#
#     stmt = (
#         select(CodeCounter)
#         .options(noload(CodeCounter.code_type))
#         .where(
#             CodeCounter.code_type_id == code_type_id,
#             (CodeCounter.company_id.is_(None) if company_id is None else CodeCounter.company_id == company_id),
#             (CodeCounter.branch_id.is_(None)  if branch_id  is None else CodeCounter.branch_id  == branch_id),
#             (CodeCounter.period_key.is_(None) if period_key is None else CodeCounter.period_key == period_key),
#         )
#         .with_for_update(of=CodeCounter)
#     )
#
#     row = s.scalar(stmt)
#     if row:
#         return row
#
#     # Create row inside a savepoint
#     try:
#         with s.begin_nested():
#             row = CodeCounter(
#                 code_type_id=code_type_id,
#                 company_id=company_id,
#                 branch_id=branch_id,
#                 period_key=period_key,
#                 last_sequence_number=0,
#             )
#             s.add(row)
#             s.flush([row])
#     except IntegrityError:
#         # Someone else created it; fall through to select with lock
#         pass
#
#     # Lock & return
#     return s.scalar(stmt)
def get_or_create_counter_row(
    *,
    code_type_id: int,
    company_id: Optional[int],
    branch_id: Optional[int],
    period_key: Optional[str],
    session: Optional[Session] = None,
) -> CodeCounter:
    """
    Return a locked row for (type, company, branch, period).
    Deterministic even if duplicates exist.
    Creates row under savepoint (safe under concurrency).
    """
    s = session or db.session

    def _select_locked():
        return (
            select(CodeCounter)
            .options(noload(CodeCounter.code_type))
            .where(
                CodeCounter.code_type_id == code_type_id,
                (CodeCounter.company_id.is_(None) if company_id is None else CodeCounter.company_id == company_id),
                (CodeCounter.branch_id.is_(None)  if branch_id  is None else CodeCounter.branch_id  == branch_id),
                (CodeCounter.period_key.is_(None) if period_key is None else CodeCounter.period_key == period_key),
            )
            .order_by(CodeCounter.last_sequence_number.desc(), CodeCounter.id.desc())
            .with_for_update(of=CodeCounter)
        )

    row = s.execute(_select_locked()).scalars().first()
    if row:
        return row

    try:
        with s.begin_nested():
            row = CodeCounter(
                code_type_id=code_type_id,
                company_id=company_id,
                branch_id=branch_id,
                period_key=period_key,
                last_sequence_number=0,
            )
            s.add(row)
            s.flush([row])
            return row
    except IntegrityError:
        pass

    row = s.execute(_select_locked()).scalars().first()
    if not row:
        raise RuntimeError("Failed to get or create CodeCounter row.")
    return row