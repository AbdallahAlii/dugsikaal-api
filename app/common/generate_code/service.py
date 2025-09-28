# # : app/common/generate_code/service.py
# from __future__ import annotations
# from datetime import date
# from typing import Optional, Dict
# import re
#
# from flask_session import Session
# from sqlalchemy import select
#
# from app.application_org.models.company import Company
# from config.database import db
# from app.common.cache.cache import get_or_build_detail
# from app.application_org.models.code_counter_model import CodeType, CodeCounter, CodeScopeEnum, ResetPolicyEnum
# from app.common.generate_code.repo import get_code_type_by_prefix, get_or_create_counter_row
#
#
# # ---- CodeType cache ----
# def _build_codetype_detail(prefix: str) -> Dict:
#     ct = get_code_type_by_prefix(prefix)
#     if not ct:
#         return {"ok": False}
#     return {
#         "ok": True,
#         "id": ct.id,
#         "prefix": ct.prefix,
#         "pattern": ct.pattern,
#         "scope": ct.scope.value,
#         "reset_policy": ct.reset_policy.value,
#         "padding": ct.padding,
#     }
#
# def _get_codetype_cached(prefix: str) -> CodeType | None:
#     d = get_or_build_detail("codetype", prefix, builder=lambda: _build_codetype_detail(prefix), ttl=3600)
#     if not d or not d.get("ok"):
#         return None
#     return CodeType(
#         id=d["id"],  # type: ignore[arg-type]
#         prefix=d["prefix"],
#         pattern=d["pattern"],
#         scope=CodeScopeEnum(d["scope"]),
#         reset_policy=ResetPolicyEnum(d["reset_policy"]),
#         padding=d["padding"],
#     )
#
# # ---- helpers ----
# def _period_key(reset: ResetPolicyEnum, today: Optional[date] = None) -> Optional[str]:
#     dt = today or date.today()
#     if reset == ResetPolicyEnum.YEARLY:
#         return f"{dt.year}"
#     if reset == ResetPolicyEnum.MONTHLY:
#         return f"{dt.year}-{dt.month:02d}"
#     return None
#
# # def _format_code(ct: CodeType, seq: int, today: Optional[date] = None) -> str:
# #     dt = today or date.today()
# #     tokens = {
# #         "PREFIX": ct.prefix,
# #         "YYYY": f"{dt.year}",
# #         "MM": f"{dt.month:02d}",
# #         "SEQ": str(seq).zfill(ct.padding or 5),
# #     }
# #     out = ct.pattern
# #     for k, v in tokens.items():
# #         out = out.replace(f"{{{k}}}", v)
# #     return out
# def _format_code(
#     ct: CodeType,
#     seq: int,
#     today: Optional[date] = None,
#     override_prefix: Optional[str] = None
# ) -> str:
#     dt = today or date.today()
#     # Use the override prefix if provided, otherwise use the CodeType's prefix
#     final_prefix = override_prefix if override_prefix is not None else ct.prefix
#     tokens = {
#         "PREFIX": final_prefix,
#         "YYYY": f"{dt.year}",
#         "MM": f"{dt.month:02d}",
#         "SEQ": str(seq).zfill(ct.padding or 5),
#     }
#     out = ct.pattern
#     for k, v in tokens.items():
#         out = out.replace(f"{{{k}}}", v)
#     return out
#
# def _resolve_partition(ct: CodeType, company_id: Optional[int], branch_id: Optional[int]):
#     if ct.scope == CodeScopeEnum.GLOBAL:
#         return None, None
#     if ct.scope == CodeScopeEnum.COMPANY:
#         if company_id is None:
#             raise ValueError("company_id required for COMPANY scope")
#         return company_id, None
#     if company_id is None or branch_id is None:
#         raise ValueError("company_id and branch_id required for BRANCH scope")
#     return company_id, branch_id
#
# # def _parse_seq_from_code(ct: CodeType, code: str) -> Optional[int]:
# #     pat = re.escape(ct.pattern)
# #     pat = pat.replace(r"\{PREFIX\}", re.escape(ct.prefix))
# #     pat = pat.replace(r"\{YYYY\}", r"\d{4}")
# #     pat = pat.replace(r"\{MM\}", r"\d{2}")
# #     pat = pat.replace(r"\{SEQ\}", r"(?P<seq>\d+)")
# #     m = re.fullmatch(pat, code.strip())
# #     if not m:
# #         return None
# #     try:
# #         return int(m.group("seq"))
# #     except Exception:
# #         return None
# def _parse_seq_from_code(ct: CodeType, code: str, override_prefix: Optional[str] = None) -> Optional[int]:
#     final_prefix = override_prefix if override_prefix is not None else ct.prefix
#     pat = re.escape(ct.pattern)
#     pat = pat.replace(r"\{PREFIX\}", re.escape(final_prefix))
#     pat = pat.replace(r"\{YYYY\}", r"\d{4}")
#     pat = pat.replace(r"\{MM\}", r"\d{2}")
#     pat = pat.replace(r"\{SEQ\}", r"(?P<seq>\d+)")
#     m = re.fullmatch(pat, code.strip())
#     if not m:
#         return None
#     try:
#         return int(m.group("seq"))
#     except Exception:
#         return None
# # ---- manual strict (for *manual* employee.code only) ----
# def ensure_manual_code_is_next_and_bump(
#     *,
#     prefix: str,
#     company_id: Optional[int],
#     branch_id: Optional[int] = None,
#     code: str,
#     today: Optional[date] = None,
# ) -> None:
#     ct = _get_codetype_cached(prefix)
#     if not ct:
#         raise ValueError(f"Unknown code type prefix: {prefix}")
#     part_company, part_branch = _resolve_partition(ct, company_id, branch_id)
#     pk = _period_key(ct.reset_policy, today)
#
#     stmt = (
#         select(CodeCounter.last_sequence_number)
#         .where(
#             CodeCounter.code_type_id == ct.id,
#             (CodeCounter.company_id.is_(None) if part_company is None else CodeCounter.company_id == part_company),
#             (CodeCounter.branch_id.is_(None)  if part_branch  is None else CodeCounter.branch_id  == part_branch),
#             (CodeCounter.period_key.is_(None) if pk is None       else CodeCounter.period_key == pk),
#         )
#     )
#     cur = db.session.execute(stmt).scalar_one_or_none() or 0
#     expected = cur + 1
#
#     seq = _parse_seq_from_code(ct, code)
#     if seq is None:
#         raise ValueError("Code does not match the configured pattern for this series.")
#     if seq != expected:
#         pad = ct.padding or 5
#         raise ValueError(f"Code must be the next in series ({expected:0{pad}d}).")
#
#     row = get_or_create_counter_row(
#         code_type_id=ct.id,
#         company_id=part_company,
#         branch_id=part_branch,
#         period_key=pk,
#     )
#     if row.last_sequence_number < seq:
#         row.last_sequence_number = seq
#         db.session.flush([row])
#
# # ---- relaxed bump (for usernames) ----
# def bump_counter_to_at_least(
#     *,
#     prefix: str,
#     company_id: Optional[int],
#     branch_id: Optional[int] = None,
#     code: str,
#     today: Optional[date] = None,
# ) -> None:
#     """
#     Set the counter to at least code.SEQ (no strict equality). Use for usernames where
#     we might skip numbers due to global uniqueness.
#     """
#     ct = _get_codetype_cached(prefix)
#     if not ct:
#         raise ValueError(f"Unknown code type prefix: {prefix}")
#     part_company, part_branch = _resolve_partition(ct, company_id, branch_id)
#     pk = _period_key(ct.reset_policy, today)
#
#     seq = _parse_seq_from_code(ct, code)
#     if seq is None:
#         raise ValueError("Code does not match the configured pattern for this series.")
#
#     row = get_or_create_counter_row(
#         code_type_id=ct.id,
#         company_id=part_company,
#         branch_id=part_branch,
#         period_key=pk,
#     )
#     if row.last_sequence_number < seq:
#         row.last_sequence_number = seq
#         db.session.flush([row])
#
# # ---- generators ----
# def generate_next_code(
#     *,
#
#     prefix: str,
#     company_id: Optional[int],
#     branch_id: Optional[int] = None,
#     today: Optional[date] = None,
# ) -> str:
#     ct = _get_codetype_cached(prefix)
#     if not ct:
#         raise ValueError(f"Unknown code type prefix: {prefix}")
#     part_company, part_branch = _resolve_partition(ct, company_id, branch_id)
#     pk = _period_key(ct.reset_policy, today)
#
#     row = get_or_create_counter_row(
#         code_type_id=ct.id,
#         company_id=part_company,
#         branch_id=part_branch,
#         period_key=pk,
#     )
#     row.last_sequence_number += 1
#     seq = row.last_sequence_number
#     db.session.flush([row])
#     return _format_code(ct, seq, today)
#
# def preview_next_code(
#     *,
#     prefix: str,
#     company_id: Optional[int],
#     branch_id: Optional[int] = None,
#     today: Optional[date] = None,
# ) -> str:
#     ct = _get_codetype_cached(prefix)
#     if not ct:
#         raise ValueError(f"Unknown code type prefix: {prefix}")
#     part_company, part_branch = _resolve_partition(ct, company_id, branch_id)
#     pk = _period_key(ct.reset_policy, today)
#
#     stmt = (
#         select(CodeCounter.last_sequence_number)
#         .where(
#             CodeCounter.code_type_id == ct.id,
#             (CodeCounter.company_id.is_(None) if part_company is None else CodeCounter.company_id == part_company),
#             (CodeCounter.branch_id.is_(None)  if part_branch  is None else CodeCounter.branch_id  == part_branch),
#             (CodeCounter.period_key.is_(None) if pk is None       else CodeCounter.period_key == pk),
#         )
#     )
#     cur = db.session.execute(stmt).scalar_one_or_none() or 0
#     return _format_code(ct, cur + 1, today)
#
#
# # ==============================================================================
# # ---- NEW: High-Level Functions for Company Username Generation ----
# # These new functions will contain the logic for using the company's prefix.
# # ==============================================================================
#
# USERNAME_CODE_TYPE_PREFIX = "USERNAME"
#
#
# def generate_next_username_for_company(company: Company, today: Optional[date] = None) -> str:
#     """Generates the next username using the company's own prefix."""
#     if not company or not company.prefix:
#         raise ValueError("Company with a valid prefix is required.")
#
#     # 1. Get the generic "USERNAME" rules
#     ct = _get_codetype_cached(USERNAME_CODE_TYPE_PREFIX)
#     if not ct:
#         raise ValueError(f"CodeType '{USERNAME_CODE_TYPE_PREFIX}' is not configured in the database.")
#
#     # 2. Get or create the counter row for this company and the "USERNAME" type
#     pk = _period_key(ct.reset_policy, today)
#     row = get_or_create_counter_row(
#         code_type_id=ct.id,
#         company_id=company.id,
#         branch_id=None,  # Scope is per-company
#         period_key=pk,
#     )
#
#     # 3. Increment sequence
#     row.last_sequence_number += 1
#     seq = row.last_sequence_number
#     db.session.flush([row])
#
#     # 4. Format the code using the company's prefix as an override
#     return _format_code(ct, seq, today, override_prefix=company.prefix)
#
#
# def preview_next_username_for_company(company: Company, today: Optional[date] = None) -> str:
#     """Previews the next username for a company without incrementing the counter."""
#     if not company or not company.prefix:
#         raise ValueError("Company with a valid prefix is required.")
#
#     ct = _get_codetype_cached(USERNAME_CODE_TYPE_PREFIX)
#     if not ct:
#         raise ValueError(f"CodeType '{USERNAME_CODE_TYPE_PREFIX}' is not configured.")
#
#     pk = _period_key(ct.reset_policy, today)
#     stmt = (
#         select(CodeCounter.last_sequence_number)
#         .where(
#             CodeCounter.code_type_id == ct.id,
#             CodeCounter.company_id == company.id,
#             CodeCounter.branch_id.is_(None),
#             (CodeCounter.period_key.is_(None) if pk is None else CodeCounter.period_key == pk),
#         )
#     )
#     cur = db.session.execute(stmt).scalar_one_or_none() or 0
#     return _format_code(ct, cur + 1, today, override_prefix=company.prefix)
#
#
# def bump_username_counter_for_company(company: Company, code: str, today: Optional[date] = None) -> None:
#     """Bumps the username counter for a company to be at least the given code's sequence."""
#     if not company or not company.prefix:
#         raise ValueError("Company with a valid prefix is required.")
#
#     ct = _get_codetype_cached(USERNAME_CODE_TYPE_PREFIX)
#     if not ct:
#         raise ValueError(f"CodeType '{USERNAME_CODE_TYPE_PREFIX}' is not configured.")
#
#     seq = _parse_seq_from_code(ct, code, override_prefix=company.prefix)
#     if seq is None:
#         raise ValueError("Username does not match the configured pattern for this series.")
#
#     pk = _period_key(ct.reset_policy, today)
#     row = get_or_create_counter_row(
#         code_type_id=ct.id,
#         company_id=company.id,
#         branch_id=None,
#         period_key=pk,
#     )
#     if row.last_sequence_number < seq:
#         row.last_sequence_number = seq
#         db.session.flush([row])
from __future__ import annotations
from datetime import date
from typing import Optional, Dict
import re

from sqlalchemy.orm import Session as SASession
from sqlalchemy import select

from app.application_org.models.company import Company
from config.database import db
from app.common.cache.cache import get_or_build_detail
from app.application_org.models.code_counter_model import CodeType, CodeCounter, CodeScopeEnum, ResetPolicyEnum
from app.common.generate_code.repo import get_code_type_by_prefix, get_or_create_counter_row


# ---- CodeType cache ----------------------------------------------------------
def _build_codetype_detail(prefix: str) -> Dict:
    ct = get_code_type_by_prefix(prefix)
    if not ct:
        return {"ok": False}
    return {
        "ok": True,
        "id": ct.id,
        "prefix": ct.prefix,
        "pattern": ct.pattern,
        "scope": ct.scope.value,
        "reset_policy": ct.reset_policy.value,
        "padding": ct.padding,
    }


def _get_codetype_cached(prefix: str) -> CodeType | None:
    d = get_or_build_detail("codetype", prefix, builder=lambda: _build_codetype_detail(prefix), ttl=3600)
    if not d or not d.get("ok"):
        return None
    return CodeType(
        id=d["id"],  # type: ignore[arg-type]
        prefix=d["prefix"],
        pattern=d["pattern"],
        scope=CodeScopeEnum(d["scope"]),
        reset_policy=ResetPolicyEnum(d["reset_policy"]),
        padding=d["padding"],
    )


# ---- helpers ----------------------------------------------------------------
def _period_key(reset: ResetPolicyEnum, today: Optional[date] = None) -> Optional[str]:
    dt = today or date.today()
    if reset == ResetPolicyEnum.YEARLY:
        return f"{dt.year}"
    if reset == ResetPolicyEnum.MONTHLY:
        return f"{dt.year}-{dt.month:02d}"
    return None


def _format_code(
    ct: CodeType,
    seq: int,
    today: Optional[date] = None,
    override_prefix: Optional[str] = None
) -> str:
    dt = today or date.today()
    final_prefix = override_prefix if override_prefix is not None else ct.prefix
    tokens = {
        "PREFIX": final_prefix,
        "YYYY": f"{dt.year}",
        "MM": f"{dt.month:02d}",
        "SEQ": str(seq).zfill(ct.padding or 5),
    }
    out = ct.pattern
    for k, v in tokens.items():
        out = out.replace(f"{{{k}}}", v)
    return out


def _resolve_partition(ct: CodeType, company_id: Optional[int], branch_id: Optional[int]):
    if ct.scope == CodeScopeEnum.GLOBAL:
        return None, None
    if ct.scope == CodeScopeEnum.COMPANY:
        if company_id is None:
            raise ValueError("company_id required for COMPANY scope")
        return company_id, None
    if company_id is None or branch_id is None:
        raise ValueError("company_id and branch_id required for BRANCH scope")
    return company_id, branch_id


def _parse_seq_from_code(ct: CodeType, code: str, override_prefix: Optional[str] = None) -> Optional[int]:
    final_prefix = override_prefix if override_prefix is not None else ct.prefix
    pat = re.escape(ct.pattern)
    pat = pat.replace(r"\{PREFIX\}", re.escape(final_prefix))
    pat = pat.replace(r"\{YYYY\}", r"\d{4}")
    pat = pat.replace(r"\{MM\}", r"\d{2}")
    pat = pat.replace(r"\{SEQ\}", r"(?P<seq>\d+)")
    m = re.fullmatch(pat, code.strip())
    if not m:
        return None
    try:
        return int(m.group("seq"))
    except Exception:
        return None


# ---- manual strict (for *manual* codes only) --------------------------------
def ensure_manual_code_is_next_and_bump(
    *,
    prefix: str,
    company_id: Optional[int],
    branch_id: Optional[int] = None,
    code: str,
    today: Optional[date] = None,
    session: Optional[SASession] = None,   # optional session
) -> None:
    ct = _get_codetype_cached(prefix)
    if not ct:
        raise ValueError(f"Unknown code type prefix: {prefix}")
    part_company, part_branch = _resolve_partition(ct, company_id, branch_id)
    pk = _period_key(ct.reset_policy, today)

    sess = session or db.session

    stmt = (
        select(CodeCounter.last_sequence_number)
        .where(
            CodeCounter.code_type_id == ct.id,
            (CodeCounter.company_id.is_(None) if part_company is None else CodeCounter.company_id == part_company),
            (CodeCounter.branch_id.is_(None)  if part_branch  is None else CodeCounter.branch_id  == part_branch),
            (CodeCounter.period_key.is_(None) if pk is None       else CodeCounter.period_key == pk),
        )
    )
    cur = sess.execute(stmt).scalar_one_or_none() or 0
    expected = cur + 1

    seq = _parse_seq_from_code(ct, code)
    if seq is None:
        raise ValueError("Code does not match the configured pattern for this series.")
    if seq != expected:
        pad = ct.padding or 5
        raise ValueError(f"Code must be the next in series ({expected:0{pad}d}).")

    row = get_or_create_counter_row(
        code_type_id=ct.id,
        company_id=part_company,
        branch_id=part_branch,
        period_key=pk,
    )
    if row.last_sequence_number < seq:
        row.last_sequence_number = seq
        sess.flush([row])


# ---- relaxed bump (for usernames) -------------------------------------------
def bump_counter_to_at_least(
    *,
    prefix: str,
    company_id: Optional[int],
    branch_id: Optional[int] = None,
    code: str,
    today: Optional[date] = None,
    session: Optional[SASession] = None,   # optional session
) -> None:
    ct = _get_codetype_cached(prefix)
    if not ct:
        raise ValueError(f"Unknown code type prefix: {prefix}")
    part_company, part_branch = _resolve_partition(ct, company_id, branch_id)
    pk = _period_key(ct.reset_policy, today)

    sess = session or db.session

    seq = _parse_seq_from_code(ct, code)
    if seq is None:
        raise ValueError("Code does not match the configured pattern for this series.")

    row = get_or_create_counter_row(
        code_type_id=ct.id,
        company_id=part_company,
        branch_id=part_branch,
        period_key=pk,
    )
    if row.last_sequence_number < seq:
        row.last_sequence_number = seq
        sess.flush([row])


# ---- generators --------------------------------------------------------------
def generate_next_code(
    *,
    prefix: str,
    company_id: Optional[int],
    branch_id: Optional[int] = None,
    today: Optional[date] = None,
    session: Optional[SASession] = None,   # optional session
) -> str:
    ct = _get_codetype_cached(prefix)
    if not ct:
        raise ValueError(f"Unknown code type prefix: {prefix}")
    part_company, part_branch = _resolve_partition(ct, company_id, branch_id)
    pk = _period_key(ct.reset_policy, today)

    sess = session or db.session

    row = get_or_create_counter_row(
        code_type_id=ct.id,
        company_id=part_company,
        branch_id=part_branch,
        period_key=pk,
    )
    row.last_sequence_number += 1
    seq = row.last_sequence_number
    sess.flush([row])
    return _format_code(ct, seq, today)


def preview_next_code(
    *,
    prefix: str,
    company_id: Optional[int],
    branch_id: Optional[int] = None,
    today: Optional[date] = None,
    session: Optional[SASession] = None,   # optional session
) -> str:
    ct = _get_codetype_cached(prefix)
    if not ct:
        raise ValueError(f"Unknown code type prefix: {prefix}")
    part_company, part_branch = _resolve_partition(ct, company_id, branch_id)
    pk = _period_key(ct.reset_policy, today)

    sess = session or db.session

    stmt = (
        select(CodeCounter.last_sequence_number)
        .where(
            CodeCounter.code_type_id == ct.id,
            (CodeCounter.company_id.is_(None) if part_company is None else CodeCounter.company_id == part_company),
            (CodeCounter.branch_id.is_(None)  if part_branch  is None else CodeCounter.branch_id  == part_branch),
            (CodeCounter.period_key.is_(None) if pk is None       else CodeCounter.period_key == pk),
        )
    )
    cur = sess.execute(stmt).scalar_one_or_none() or 0
    return _format_code(ct, cur + 1, today)


# ==============================================================================
# High-level company username helpers (same behavior; optional session not needed)
# ==============================================================================
USERNAME_CODE_TYPE_PREFIX = "USERNAME"


def generate_next_username_for_company(company: Company, today: Optional[date] = None) -> str:
    if not company or not company.prefix:
        raise ValueError("Company with a valid prefix is required.")

    ct = _get_codetype_cached(USERNAME_CODE_TYPE_PREFIX)
    if not ct:
        raise ValueError(f"CodeType '{USERNAME_CODE_TYPE_PREFIX}' is not configured in the database.")

    pk = _period_key(ct.reset_policy, today)
    row = get_or_create_counter_row(
        code_type_id=ct.id,
        company_id=company.id,
        branch_id=None,
        period_key=pk,
    )
    row.last_sequence_number += 1
    seq = row.last_sequence_number
    db.session.flush([row])
    return _format_code(ct, seq, today, override_prefix=company.prefix)


def preview_next_username_for_company(company: Company, today: Optional[date] = None) -> str:
    if not company or not company.prefix:
        raise ValueError("Company with a valid prefix is required.")

    ct = _get_codetype_cached(USERNAME_CODE_TYPE_PREFIX)
    if not ct:
        raise ValueError(f"CodeType '{USERNAME_CODE_TYPE_PREFIX}' is not configured.")

    pk = _period_key(ct.reset_policy, today)
    stmt = (
        select(CodeCounter.last_sequence_number)
        .where(
            CodeCounter.code_type_id == ct.id,
            CodeCounter.company_id == company.id,
            CodeCounter.branch_id.is_(None),
            (CodeCounter.period_key.is_(None) if pk is None else CodeCounter.period_key == pk),
        )
    )
    cur = db.session.execute(stmt).scalar_one_or_none() or 0
    return _format_code(ct, cur + 1, today, override_prefix=company.prefix)


def bump_username_counter_for_company(company: Company, code: str, today: Optional[date] = None) -> None:
    if not company or not company.prefix:
        raise ValueError("Company with a valid prefix is required.")

    ct = _get_codetype_cached(USERNAME_CODE_TYPE_PREFIX)
    if not ct:
        raise ValueError(f"CodeType '{USERNAME_CODE_TYPE_PREFIX}' is not configured.")

    seq = _parse_seq_from_code(ct, code, override_prefix=company.prefix)
    if seq is None:
        raise ValueError("Username does not match the configured pattern for this series.")

    pk = _period_key(ct.reset_policy, today)
    row = get_or_create_counter_row(
        code_type_id=ct.id,
        company_id=company.id,
        branch_id=None,
        period_key=pk,
    )
    if row.last_sequence_number < seq:
        row.last_sequence_number = seq
        db.session.flush([row])
