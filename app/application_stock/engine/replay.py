# #
# # # app/application_stock/engine/replay.py
# # from __future__ import annotations
# #
# # import logging
# # from datetime import datetime, timedelta, timezone
# # from decimal import Decimal
# # from typing import List, Optional, Set, Tuple
# #
# # from sqlalchemy import select, and_, or_, asc
# # from sqlalchemy.orm import Session
# #
# # from app.application_stock.stock_models import StockLedgerEntry
# # from app.application_stock.engine.sle_writer import append_sle, cancel_sle
# # from app.application_stock.engine.types import SLEIntent, AdjustmentType
# # from app.application_stock.engine.locks import lock_pairs
# #
# # logger = logging.getLogger(__name__)
# #
# # def _stream_strictly_after(
# #     s: Session,
# #     *,
# #     company_id: int,
# #     item_id: int,
# #     warehouse_id: int,
# #     start_dt: datetime,
# #     exclude_doc_types: Optional[Set[int]] = None,
# # ) -> List[StockLedgerEntry]:
# #     """
# #     All NON-CANCELLED SLEs STRICTLY AFTER start_dt, ordered by (date, time, id) ASC.
# #     Optionally exclude specific document types.
# #     """
# #     exclude_doc_types = exclude_doc_types or set()
# #
# #     if start_dt.tzinfo is None:
# #         start_dt = start_dt.replace(tzinfo=timezone.utc)
# #         logger.info("_stream_strictly_after: Made start_dt timezone-aware: %s", start_dt)
# #
# #     logger.info("_stream_strictly_after: Querying for SLEs after %s (timezone: %s)", start_dt, start_dt.tzinfo)
# #     logger.info("_stream_strictly_after: Excluding doc_types: %s", exclude_doc_types)
# #
# #     q = (
# #         select(StockLedgerEntry)
# #         .where(
# #             StockLedgerEntry.company_id == company_id,
# #             StockLedgerEntry.item_id == item_id,
# #             StockLedgerEntry.warehouse_id == warehouse_id,
# #             StockLedgerEntry.is_cancelled == False,  # noqa: E712
# #             StockLedgerEntry.doc_type_id.notin_(exclude_doc_types),
# #             or_(
# #                 StockLedgerEntry.posting_date > start_dt.date(),
# #                 and_(
# #                     StockLedgerEntry.posting_date == start_dt.date(),
# #                     StockLedgerEntry.posting_time > start_dt,
# #                 ),
# #             ),
# #         )
# #         .order_by(
# #             asc(StockLedgerEntry.posting_date),
# #             asc(StockLedgerEntry.posting_time),
# #             asc(StockLedgerEntry.id),
# #         )
# #     )
# #
# #     result = list(s.execute(q).scalars().all())
# #     logger.info("_stream_strictly_after: Found %d SLEs after %s", len(result), start_dt)
# #     for sle in result:
# #         tzinfo = sle.posting_time.tzinfo if sle.posting_time else None
# #         logger.info(
# #             "SLE ID %s - posting_time: %s (tz: %s), actual_qty: %s",
# #             sle.id, sle.posting_time, tzinfo, sle.actual_qty
# #         )
# #     return result
# #
# # def _as_intent_from_sle(sle: StockLedgerEntry, index: int = 0) -> SLEIntent:
# #     """
# #     Build an SLEIntent from an existing SLE row for replay write-back.
# #     A tiny index-based µs offset preserves strict chronology when multiple rows share the same timestamp.
# #     """
# #     offset_dt = sle.posting_time + timedelta(microseconds=index)
# #     logger.info("_as_intent_from_sle: Creating intent from SLE ID %s, offset_dt: %s", sle.id, offset_dt)
# #
# #     return SLEIntent(
# #         company_id=sle.company_id,
# #         branch_id=sle.branch_id,
# #         item_id=sle.item_id,
# #         warehouse_id=sle.warehouse_id,
# #         posting_dt=offset_dt,
# #         actual_qty=sle.actual_qty,
# #         incoming_rate=sle.incoming_rate,
# #         outgoing_rate=sle.outgoing_rate,
# #         stock_value_difference=sle.stock_value_difference or Decimal("0"),
# #         doc_type_id=sle.doc_type_id,
# #         doc_id=sle.doc_id,
# #         doc_row_id=sle.doc_row_id,
# #         adjustment_type=AdjustmentType.NORMAL,
# #         meta={},
# #     )
# #
# # def repost_from(
# #     *,
# #     s: Session,
# #     company_id: int,
# #     item_id: int,
# #     warehouse_id: int,
# #     start_dt: datetime,
# #     exclude_doc_types: Optional[Set[int]] = None,
# # ) -> None:
# #     """
# #     Recompute valuation stream STRICTLY AFTER start_dt for (company,item,warehouse).
# #     - Cancels forward rows and re-appends them deterministically.
# #     - Skips any rows whose doc_type_id is in exclude_doc_types.
# #     """
# #     exclude_doc_types = exclude_doc_types or set()
# #
# #     logger.info("repost_from: Starting for item=%s, wh=%s, start_dt=%s", item_id, warehouse_id, start_dt)
# #     logger.info("repost_from: Timezone info - start_dt: %s", start_dt.tzinfo if start_dt.tzinfo else "None")
# #     logger.info("repost_from: Excluding doc types: %s", exclude_doc_types)
# #
# #     with lock_pairs(s, [(item_id, warehouse_id)]):
# #         stream = _stream_strictly_after(
# #             s,
# #             company_id=company_id,
# #             item_id=item_id,
# #             warehouse_id=warehouse_id,
# #             start_dt=start_dt,
# #             exclude_doc_types=exclude_doc_types,
# #         )
# #         logger.info("repost_from: Found %d SLEs to rebuild after start_dt=%s", len(stream), start_dt)
# #
# #         if not stream:
# #             logger.info("repost_from: No SLEs found to rebuild, returning early")
# #             return
# #
# #         # Cancel forward rows (except excluded)
# #         to_rebuild: List[StockLedgerEntry] = []
# #         for row in stream:
# #             if row.doc_type_id in exclude_doc_types:
# #                 logger.info("repost_from: Skipping SLE ID %s due to excluded doc_type %s", row.id, row.doc_type_id)
# #                 continue
# #             logger.info("repost_from: Cancelling SLE ID %s with qty %s", row.id, row.actual_qty)
# #             cancel_sle(s, row)
# #             to_rebuild.append(row)
# #
# #         if not to_rebuild:
# #             logger.info("repost_from: No SLEs found to rebuild after filtering.")
# #             return
# #
# #         logger.info("repost_from: Rebuilding %d SLEs", len(to_rebuild))
# #         BATCH_SIZE = 100
# #         for i in range(0, len(to_rebuild), BATCH_SIZE):
# #             batch = to_rebuild[i:i + BATCH_SIZE]
# #             for idx, row in enumerate(batch):
# #                 logger.info("repost_from: Processing SLE %d/%d - ID %s", i + idx + 1, len(to_rebuild), row.id)
# #                 intent = _as_intent_from_sle(row, idx)
# #                 append_sle(s, intent, batch_index=idx)  # FIX: preserve µs ordering here as well
# #             s.flush()
# #
# #         logger.info("repost_from: Completed successfully")
# # app/application_stock/engine/replay.py
# from __future__ import annotations
#
# import logging
# from datetime import datetime, timedelta, timezone
# from decimal import Decimal
# from typing import List, Optional, Set
#
# from sqlalchemy import select, and_, or_, asc
# from sqlalchemy.orm import Session
#
# from app.application_stock.stock_models import StockLedgerEntry
# from app.application_stock.engine.sle_writer import append_sle, cancel_sle
# from app.application_stock.engine.types import SLEIntent, AdjustmentType
# from app.application_stock.engine.locks import lock_pairs
#
# logger = logging.getLogger(__name__)
#
# def _stream_strictly_after(
#     s: Session,
#     *,
#     company_id: int,
#     item_id: int,
#     warehouse_id: int,
#     start_dt: datetime,
#     exclude_doc_types: Optional[Set[int]] = None,
# ) -> List[StockLedgerEntry]:
#     """
#     Fetch all NON-CANCELLED SLEs strictly after start_dt (UTC-normalized),
#     ordered by posting_date, posting_time, id.
#     """
#     exclude_doc_types = exclude_doc_types or set()
#
#     # Ensure start_dt is timezone-aware and normalized to UTC
#     if start_dt.tzinfo is None:
#         start_dt = start_dt.replace(tzinfo=timezone.utc)
#         logger.info("Made start_dt timezone-aware: %s", start_dt)
#     else:
#         start_dt = start_dt.astimezone(timezone.utc)
#
#     logger.info("Querying SLEs after %s (UTC)", start_dt)
#
#     q = (
#         select(StockLedgerEntry)
#         .where(
#             StockLedgerEntry.company_id == company_id,
#             StockLedgerEntry.item_id == item_id,
#             StockLedgerEntry.warehouse_id == warehouse_id,
#             StockLedgerEntry.is_cancelled == False,  # noqa: E712
#             StockLedgerEntry.doc_type_id.notin_(exclude_doc_types),
#             or_(
#                 StockLedgerEntry.posting_date > start_dt.date(),
#                 and_(
#                     StockLedgerEntry.posting_date == start_dt.date(),
#                     StockLedgerEntry.posting_time > start_dt,
#                 ),
#             ),
#         )
#         .order_by(
#             asc(StockLedgerEntry.posting_date),
#             asc(StockLedgerEntry.posting_time),
#             asc(StockLedgerEntry.id),
#         )
#     )
#
#     result = list(s.execute(q).scalars().all())
#     logger.info("Found %d SLEs after %s", len(result), start_dt)
#     return result
#
#
# def _as_intent_from_sle(sle: StockLedgerEntry, index: int = 0) -> SLEIntent:
#     """
#     Build an SLEIntent for replay. Adds microsecond offsets to preserve strict order.
#     """
#     posting_dt = sle.posting_time
#     if posting_dt.tzinfo is None:
#         posting_dt = posting_dt.replace(tzinfo=timezone.utc)
#     posting_dt += timedelta(microseconds=index)
#
#     return SLEIntent(
#         company_id=sle.company_id,
#         branch_id=sle.branch_id,
#         item_id=sle.item_id,
#         warehouse_id=sle.warehouse_id,
#         posting_dt=posting_dt,
#         actual_qty=sle.actual_qty,
#         incoming_rate=sle.incoming_rate,
#         outgoing_rate=sle.outgoing_rate,
#         stock_value_difference=sle.stock_value_difference or Decimal("0"),
#         doc_type_id=sle.doc_type_id,
#         doc_id=sle.doc_id,
#         doc_row_id=sle.doc_row_id,
#         adjustment_type=AdjustmentType.NORMAL,
#         meta={},
#     )
#
#
# def repost_from(
#     *,
#     s: Session,
#     company_id: int,
#     item_id: int,
#     warehouse_id: int,
#     start_dt: datetime,
#     exclude_doc_types: Optional[Set[int]] = None,
# ) -> None:
#     """
#     Recompute valuation stream STRICTLY AFTER start_dt for (company,item,warehouse).
#     Ensures atomic, deterministic replay with UTC normalization.
#     """
#     exclude_doc_types = exclude_doc_types or set()
#
#     # UTC normalize
#     if start_dt.tzinfo is None:
#         start_dt = start_dt.replace(tzinfo=timezone.utc)
#     else:
#         start_dt = start_dt.astimezone(timezone.utc)
#
#     logger.info(
#         "Reposting from %s for item %s, warehouse %s",
#         start_dt, item_id, warehouse_id
#     )
#
#     with lock_pairs(s, [(item_id, warehouse_id)]):
#         stream = _stream_strictly_after(
#             s,
#             company_id=company_id,
#             item_id=item_id,
#             warehouse_id=warehouse_id,
#             start_dt=start_dt,
#             exclude_doc_types=exclude_doc_types
#         )
#
#         if not stream:
#             logger.info("No SLEs to rebuild after %s", start_dt)
#             return
#
#         # Cancel and collect SLEs for replay
#         to_rebuild = []
#         for sle in stream:
#             if sle.doc_type_id in exclude_doc_types:
#                 continue
#             cancel_sle(s, sle)
#             to_rebuild.append(sle)
#
#         # Rebuild deterministically
#         BATCH_SIZE = 100
#         for i in range(0, len(to_rebuild), BATCH_SIZE):
#             batch = to_rebuild[i:i + BATCH_SIZE]
#             for idx, sle in enumerate(batch):
#                 intent = _as_intent_from_sle(sle, idx)
#                 append_sle(s, intent, batch_index=idx)
#             s.flush()
#
#     logger.info("Replay completed successfully")
# app/application_stock/engine/replay.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Set

from sqlalchemy import select, and_, or_, asc
from sqlalchemy.orm import Session

from app.application_stock.stock_models import StockLedgerEntry
from app.application_stock.engine.sle_writer import append_sle, cancel_sle
from app.application_stock.engine.types import SLEIntent, AdjustmentType
from app.application_stock.engine.locks import lock_pairs

logger = logging.getLogger(__name__)


def _stream_strictly_after(
    s: Session,
    *,
    company_id: int,
    item_id: int,
    warehouse_id: int,
    start_dt: datetime,
    exclude_doc_types: Optional[Set[int]] = None,
) -> List[StockLedgerEntry]:
    """
    Fetch all NON-CANCELLED SLEs strictly after start_dt (UTC-normalized),
    ordered by posting_date, posting_time, id.
    """
    exclude_doc_types = exclude_doc_types or set()

    # Ensure start_dt is timezone-aware and normalized to UTC
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
        logger.info("Made start_dt timezone-aware: %s", start_dt)
    else:
        start_dt = start_dt.astimezone(timezone.utc)

    logger.info("Querying SLEs after %s (UTC)", start_dt)

    q = (
        select(StockLedgerEntry)
        .where(
            StockLedgerEntry.company_id == company_id,
            StockLedgerEntry.item_id == item_id,
            StockLedgerEntry.warehouse_id == warehouse_id,
            StockLedgerEntry.is_cancelled == False,  # noqa: E712
            or_(
                StockLedgerEntry.posting_date > start_dt.date(),
                and_(
                    StockLedgerEntry.posting_date == start_dt.date(),
                    StockLedgerEntry.posting_time > start_dt,
                ),
            ),
        )
        .order_by(
            asc(StockLedgerEntry.posting_date),
            asc(StockLedgerEntry.posting_time),
            asc(StockLedgerEntry.id),
        )
    )

    if exclude_doc_types:
        q = q.where(StockLedgerEntry.doc_type_id.notin_(exclude_doc_types))

    result = list(s.execute(q).scalars().all())
    logger.info("Found %d SLEs after %s", len(result), start_dt)
    return result


def _as_intent_from_sle(sle: StockLedgerEntry, index: int = 0) -> SLEIntent:
    """
    Build an SLEIntent for replay. Adds microsecond offsets to preserve strict order.
    """
    posting_dt = sle.posting_time
    if posting_dt.tzinfo is None:
        posting_dt = posting_dt.replace(tzinfo=timezone.utc)
    posting_dt += timedelta(microseconds=index)

    return SLEIntent(
        company_id=sle.company_id,
        branch_id=sle.branch_id,
        item_id=sle.item_id,
        warehouse_id=sle.warehouse_id,
        posting_dt=posting_dt,
        actual_qty=sle.actual_qty,
        incoming_rate=sle.incoming_rate,
        outgoing_rate=sle.outgoing_rate,
        stock_value_difference=sle.stock_value_difference or Decimal("0"),
        doc_type_id=sle.doc_type_id,
        doc_id=sle.doc_id,
        doc_row_id=sle.doc_row_id,
        adjustment_type=AdjustmentType.NORMAL,
        meta={},
    )


def repost_from(
    *,
    s: Session,
    company_id: int,
    item_id: int,
    warehouse_id: int,
    start_dt: datetime,
    exclude_doc_types: Optional[Set[int]] = None,
) -> None:
    """
    Recompute valuation stream STRICTLY AFTER start_dt for (company,item,warehouse).
    Ensures atomic, deterministic replay with UTC normalization.
    """
    exclude_doc_types = exclude_doc_types or set()

    # UTC normalize
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    else:
        start_dt = start_dt.astimezone(timezone.utc)

    logger.info(
        "Reposting from %s for item %s, warehouse %s",
        start_dt, item_id, warehouse_id
    )

    with lock_pairs(s, [(item_id, warehouse_id)]):
        stream = _stream_strictly_after(
            s,
            company_id=company_id,
            item_id=item_id,
            warehouse_id=warehouse_id,
            start_dt=start_dt,
            exclude_doc_types=exclude_doc_types
        )

        if not stream:
            logger.info("No SLEs to rebuild after %s", start_dt)
            return

        # Cancel and collect SLEs for replay
        to_rebuild = []
        for sle in stream:
            if exclude_doc_types and sle.doc_type_id in exclude_doc_types:
                continue
            cancel_sle(s, sle)
            to_rebuild.append(sle)

        # Rebuild deterministically
        BATCH_SIZE = 100
        for i in range(0, len(to_rebuild), BATCH_SIZE):
            batch = to_rebuild[i:i + BATCH_SIZE]
            for idx, sle in enumerate(batch):
                intent = _as_intent_from_sle(sle, idx)
                append_sle(s, intent, batch_index=idx)
            s.flush()

    logger.info("Replay completed successfully")
