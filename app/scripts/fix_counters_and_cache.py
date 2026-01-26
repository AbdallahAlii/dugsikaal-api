# app/scripts/fix_counters_and_cache.py
from __future__ import annotations

import os
import sys
import argparse
import logging
from typing import Optional, Iterable, Tuple, List, Any

from sqlalchemy import select, text, func
from sqlalchemy.orm import noload
from sqlalchemy.exc import IntegrityError

# -----------------------------------------------------------------------------
# Ensure imports work when running as: python app/scripts/fix_counters_and_cache.py ...
# -----------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config.database import db
from app.common.cache.cache import bump_version
from app.common.cache.cache_keys import detail_version_key
from app.application_org.models.code_counter_model import (
    CodeType,
    CodeScopeEnum,
    CodeCounter,
    ResetPolicyEnum,
)
from app.common.generate_code.service import _parse_seq_from_code, _period_key
from app.common.generate_code.repo import get_or_create_counter_row

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fix_tool")


def app_context():
    """Create app context (minimal)."""
    from app import create_app
    app = create_app()
    return app.app_context()


# -----------------------------------------------------------------------------
# CACHE
# -----------------------------------------------------------------------------
def invalidate_codetypes(prefixes: Optional[List[str]] = None, all_flags: bool = False) -> None:
    """
    Bumps the detail version for the given prefixes (or all).
    """
    if all_flags:
        log.info("Fetching all CodeType prefixes from DB...")
        prefixes = db.session.execute(select(CodeType.prefix)).scalars().all()

    if not prefixes:
        log.warning("No prefixes specified.")
        return

    count = 0
    for p in prefixes:
        k = detail_version_key("codetype", p)
        v = bump_version(k)
        log.info("Bumped cache for '%s' -> v%s", p, v)
        count += 1

    log.info("Invalidated %s CodeType caches.", count)


# -----------------------------------------------------------------------------
# COUNTER REPAIR (from document table max code)
# -----------------------------------------------------------------------------
def repair_counter(
    prefix: str,
    table: str,
    field: str,
    company_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    dry_run: bool = False,
) -> None:
    """
    Reads CodeType, scans max(code) from a table, parses seq, bumps CodeCounter for CURRENT period.
    Good for fixing corrupted counters, but NOT a scope migration by itself.
    """
    ct = db.session.scalar(select(CodeType).where(CodeType.prefix == prefix))
    if not ct:
        log.error("CodeType '%s' not found.", prefix)
        return

    log.info("Target: CodeType %s (Scope: %s)", ct.prefix, ct.scope.value)

    # validate args
    if ct.scope == CodeScopeEnum.COMPANY and not company_id:
        log.error("Error: --company-id is required for scope %s", ct.scope.value)
        return
    if ct.scope == CodeScopeEnum.BRANCH and (not company_id or not branch_id):
        log.error("Error: --company-id AND --branch-id are required for scope %s", ct.scope.value)
        return

    # Validate identifiers (basic guard)
    if not table.isidentifier() or not field.isidentifier():
        log.error("Invalid table or field name.")
        return

    where_clauses: List[str] = []
    params: dict[str, Any] = {}

    if ct.scope == CodeScopeEnum.COMPANY:
        where_clauses.append("company_id = :cid")
        params["cid"] = company_id
    elif ct.scope == CodeScopeEnum.BRANCH:
        where_clauses.append("branch_id = :bid")
        params["bid"] = branch_id
        if company_id:
            where_clauses.append("company_id = :cid")
            params["cid"] = company_id

    like_pat = f"{prefix}%"
    where_clauses.append(f"{field} LIKE :pat")
    params["pat"] = like_pat

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    sql = f"SELECT MAX({field}) as max_code FROM {table} WHERE {where_sql}"

    log.info("Executing: %s | Params: %s", sql, params)
    result = db.session.execute(text(sql), params).fetchone()

    if not result or not result.max_code:
        log.warning("No existing records found to derive counter from.")
        return

    max_code = result.max_code
    log.info("Found Max Code in DB: %s", max_code)

    seq = _parse_seq_from_code(ct, max_code)
    if seq is None:
        log.warning("Could not parse sequence from code '%s' using pattern '%s'.", max_code, ct.pattern)
        return

    log.info("Parsed Sequence: %s", seq)

    import datetime
    today = datetime.date.today()
    pk = _period_key(ct.reset_policy, today)

    if ct.reset_policy == ResetPolicyEnum.YEARLY and str(today.year) not in max_code:
        log.warning(
            "Max code '%s' does not look like current year %s; skipping current-period repair.",
            max_code, today.year
        )
        return

    row = get_or_create_counter_row(
        code_type_id=ct.id,
        company_id=params.get("cid"),
        branch_id=params.get("bid"),
        period_key=pk,
    )

    log.info("Current Counter (DB): %s", row.last_sequence_number)

    if row.last_sequence_number < seq:
        log.info("Repairing: Updating counter from %s -> %s", row.last_sequence_number, seq)
        if not dry_run:
            row.last_sequence_number = seq
            db.session.add(row)
            db.session.commit()
            log.info("Done.")
        else:
            log.info("[Dry Run] Change not committed.")
    else:
        log.info("Counter is already ahead or equal. No repair needed.")


# -----------------------------------------------------------------------------
# SCOPE MIGRATION: BRANCH -> COMPANY (fixes your exact production problem)
# -----------------------------------------------------------------------------
def _lock_rows_for_partition(
    *,
    code_type_id: int,
    company_id: int,
    period_key: Optional[str],
    branch_is_null: Optional[bool],  # True => branch_id is NULL, False => NOT NULL
) -> List[CodeCounter]:
    stmt = (
        select(CodeCounter)
        .options(noload(CodeCounter.code_type))
        .where(
            CodeCounter.code_type_id == code_type_id,
            CodeCounter.company_id == company_id,
            (CodeCounter.period_key.is_(None) if period_key is None else CodeCounter.period_key == period_key),
        )
    )
    if branch_is_null is True:
        stmt = stmt.where(CodeCounter.branch_id.is_(None))
    elif branch_is_null is False:
        stmt = stmt.where(CodeCounter.branch_id.is_not(None))

    # Lock rows so no concurrent writer modifies while we migrate
    stmt = stmt.with_for_update(of=CodeCounter)
    return list(db.session.scalars(stmt).all())


def migrate_branch_to_company(
    *,
    prefixes: Optional[List[str]] = None,
    all_company_scoped: bool = False,
    company_id: Optional[int] = None,
    period_key: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """
    For CodeTypes that are now COMPANY scope, migrate any existing BRANCH counter rows:
      - ensure company row exists (branch_id NULL)
      - set company row seq = max(company rows + branch rows)
      - delete branch rows
      - delete duplicate company rows (keep highest seq)
    """
    # pick CodeTypes
    if prefixes:
        cts = db.session.execute(select(CodeType).where(CodeType.prefix.in_(prefixes))).scalars().all()
    elif all_company_scoped:
        cts = db.session.execute(select(CodeType).where(CodeType.scope == CodeScopeEnum.COMPANY)).scalars().all()
    else:
        log.error("Provide --prefixes OR --all-company-scoped.")
        return

    if not cts:
        log.warning("No CodeTypes matched.")
        return

    changed_partitions = 0
    deleted_branch_rows = 0
    deleted_dup_company_rows = 0
    created_company_rows = 0
    updated_company_rows = 0

    # We do everything in one transaction; --dry-run rolls back at end.
    try:
        for ct in cts:
            if ct.scope != CodeScopeEnum.COMPANY:
                log.info("Skipping prefix=%s (scope=%s)", ct.prefix, ct.scope.value)
                continue

            # find partitions that have branch rows
            part_stmt = (
                select(CodeCounter.company_id, CodeCounter.period_key)
                .where(CodeCounter.code_type_id == ct.id)
                .where(CodeCounter.branch_id.is_not(None))
            )
            if company_id is not None:
                part_stmt = part_stmt.where(CodeCounter.company_id == company_id)
            if period_key is not None:
                part_stmt = part_stmt.where(
                    CodeCounter.period_key.is_(None) if period_key is None else CodeCounter.period_key == period_key
                )

            part_stmt = part_stmt.group_by(CodeCounter.company_id, CodeCounter.period_key)
            partitions: List[Tuple[Optional[int], Optional[str]]] = list(db.session.execute(part_stmt).all())

            if not partitions:
                log.info("No branch rows to migrate for prefix=%s (ct_id=%s).", ct.prefix, ct.id)
                continue

            log.info("Migrating prefix=%s (ct_id=%s): %s partitions", ct.prefix, ct.id, len(partitions))

            for (cid, pk) in partitions:
                if cid is None:
                    log.warning("Skipping ct=%s partition with company_id=NULL (unexpected).", ct.prefix)
                    continue

                # isolate each partition in a SAVEPOINT so one failure doesn't kill all
                with db.session.begin_nested():
                    # lock existing rows
                    company_rows = _lock_rows_for_partition(
                        code_type_id=ct.id, company_id=cid, period_key=pk, branch_is_null=True
                    )
                    branch_rows = _lock_rows_for_partition(
                        code_type_id=ct.id, company_id=cid, period_key=pk, branch_is_null=False
                    )

                    if not branch_rows:
                        continue

                    max_seq = 0
                    if company_rows:
                        max_seq = max(max_seq, max(r.last_sequence_number for r in company_rows))
                    if branch_rows:
                        max_seq = max(max_seq, max(r.last_sequence_number for r in branch_rows))

                    # choose / ensure canonical company row
                    canonical: Optional[CodeCounter] = None
                    if company_rows:
                        # keep the "best" row (highest seq, newest id)
                        canonical = sorted(
                            company_rows,
                            key=lambda r: (r.last_sequence_number, r.id),
                            reverse=True,
                        )[0]
                    else:
                        canonical = CodeCounter(
                            code_type_id=ct.id,
                            company_id=cid,
                            branch_id=None,
                            period_key=pk,
                            last_sequence_number=0,
                        )
                        db.session.add(canonical)
                        db.session.flush([canonical])
                        created_company_rows += 1

                    # update canonical seq if needed
                    before = canonical.last_sequence_number
                    after = max(before, max_seq)
                    if after != before:
                        canonical.last_sequence_number = after
                        db.session.flush([canonical])
                        updated_company_rows += 1

                    # delete duplicate company rows (keep canonical)
                    for r in company_rows:
                        if r.id != canonical.id:
                            db.session.delete(r)
                            deleted_dup_company_rows += 1

                    # delete branch rows
                    for r in branch_rows:
                        db.session.delete(r)
                        deleted_branch_rows += 1

                    changed_partitions += 1
                    log.info(
                        "✅ ct=%s co=%s per=%s | set company_seq=%s | deleted branch_rows=%s dup_company=%s",
                        ct.prefix, cid, pk, canonical.last_sequence_number, len(branch_rows),
                        max(0, len(company_rows) - 1),
                    )

        if dry_run:
            db.session.rollback()
            log.info("DRY RUN: rolled back all changes.")
        else:
            db.session.commit()
            log.info("Committed all changes.")

        log.info(
            "SUMMARY: changed_partitions=%s created_company_rows=%s updated_company_rows=%s "
            "deleted_branch_rows=%s deleted_dup_company_rows=%s",
            changed_partitions, created_company_rows, updated_company_rows,
            deleted_branch_rows, deleted_dup_company_rows,
        )

    except Exception as e:
        db.session.rollback()
        log.exception("Migration failed; rolled back. err=%s", e)
        raise


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="ERP Cache & Counter Manager")
    subparsers = parser.add_subparsers(dest="command")

    # Invalidate CodeType cache
    p_inv = subparsers.add_parser("invalidate-codetype", help="Invalidate CodeType cache")
    p_inv.add_argument("--prefixes", nargs="+", help="List of prefixes")
    p_inv.add_argument("--all", action="store_true", help="Invalidate ALL CodeTypes")

    # Repair counter (scan table)
    p_rep = subparsers.add_parser("repair-counter", help="Repair CodeCounter from max DB value (single period)")
    p_rep.add_argument("--prefix", required=True)
    p_rep.add_argument("--table", required=True, help="DB Table name (e.g. purchase_invoices)")
    p_rep.add_argument("--field", required=True, help="DB Column name (e.g. code)")
    p_rep.add_argument("--company-id", type=int)
    p_rep.add_argument("--branch-id", type=int)
    p_rep.add_argument("--dry-run", action="store_true")

    # NEW: migrate counters BRANCH -> COMPANY
    p_mig = subparsers.add_parser("migrate-branch-to-company", help="Migrate CodeCounter rows from BRANCH partitions to COMPANY")
    p_mig.add_argument("--prefixes", nargs="+", help="Only these CodeType prefixes")
    p_mig.add_argument("--all-company-scoped", action="store_true", help="Migrate ALL CodeTypes where scope=COMPANY")
    p_mig.add_argument("--company-id", type=int, help="Limit to a single company_id")
    p_mig.add_argument("--period-key", type=str, help="Limit to a single period_key (e.g. 2025 or 2025-12)")
    p_mig.add_argument("--dry-run", action="store_true", help="Show actions but do not commit changes")

    args = parser.parse_args()

    with app_context():
        if args.command == "invalidate-codetype":
            invalidate_codetypes(args.prefixes, args.all)

        elif args.command == "repair-counter":
            repair_counter(
                prefix=args.prefix,
                table=args.table,
                field=args.field,
                company_id=args.company_id,
                branch_id=args.branch_id,
                dry_run=args.dry_run,
            )

        elif args.command == "migrate-branch-to-company":
            migrate_branch_to_company(
                prefixes=args.prefixes,
                all_company_scoped=args.all_company_scoped,
                company_id=args.company_id,
                period_key=args.period_key,
                dry_run=args.dry_run,
            )

        else:
            parser.print_help()


if __name__ == "__main__":
    main()
