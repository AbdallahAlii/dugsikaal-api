# from __future__ import annotations
# from typing import Optional
# import enum
#
# from sqlalchemy import UniqueConstraint, Index, CheckConstraint, ForeignKey
# from sqlalchemy.orm import Mapped, mapped_column, relationship
#
# from config.database import db
# from app.common.models.base import BaseModel
#
#
# # ----- Alerts you want to support -----
# class InventoryEventTypeEnum(str, enum.Enum):
#     EXPIRY_SOON       = "ExpirySoon"
#     WARRANTY_END_SOON = "WarrantyEndSoon"
#
#
# class ItemExpiryDate(BaseModel):
#     """
#     Tracks the expiration date for a specific item lot in a specific warehouse.
#     This is a core table for managing shelf life at the most granular level.
#     """
#     __tablename__ = "item_expiry_dates"
#
#     company_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("companies.id", ondelete="CASCADE"),
#                                             nullable=False, index=True)
#     item_id: Mapped[int]    = mapped_column(db.BigInteger, ForeignKey("items.id", ondelete="CASCADE"),
#                                             nullable=False, index=True)
#     # The warehouse where this specific batch is stored.
#     warehouse_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("warehouses.id", ondelete="CASCADE"),
#                                               nullable=False, index=True)
#     batch_number: Mapped[str] = mapped_column(db.String(100), nullable=False)
#     expiration_date: Mapped[db.Date] = mapped_column(db.Date, nullable=False, index=True)
#
#     # relations
#     item: Mapped["Item"] = relationship(back_populates="expiry_dates", lazy="select")
#     warehouse: Mapped["Warehouse"] = relationship("Warehouse", lazy="select")
#
#     __table_args__ = (
#         # Unique constraint to prevent duplicate batches within the same company, item, and warehouse.
#         UniqueConstraint("company_id", "item_id", "warehouse_id", "batch_number", name="uq_item_expiry_date"),
#         Index("ix_item_expiry_dates_company_expiry", "company_id", "expiration_date"),
#     )
#
#     def __repr__(self) -> str:
#         return f"<ItemExpiryDate id={self.id} item={self.item_id} warehouse={self.warehouse_id} batch={self.batch_number!r} expiry={self.expiration_date}>"
#
#
# class ItemWarranty(BaseModel):
#     """
#     Minimal warranty records per item. This is the transactional table.
#     It records a specific warranty event, with a start date and duration.
#     """
#     __tablename__ = "item_warranties"
#
#     company_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("companies.id", ondelete="CASCADE"),
#                                             nullable=False, index=True)
#     item_id: Mapped[int]    = mapped_column(db.BigInteger, ForeignKey("items.id", ondelete="CASCADE"),
#                                             nullable=False, index=True)
#
#     start_date: Mapped[db.Date] = mapped_column(db.Date, nullable=False)
#     duration_months: Mapped[int] = mapped_column(db.Integer, nullable=False, default=12)
#     terms: Mapped[Optional[str]] = mapped_column(db.String(255))
#
#     item: Mapped["Item"] = relationship(back_populates="warranties", lazy="select")
#
#     __table_args__ = (
#         UniqueConstraint("company_id", "item_id", "start_date", name="uq_item_warranty"),
#         CheckConstraint("duration_months >= 0", name="ck_warranty_duration_nonneg"),
#         Index("ix_item_warranties_company_start", "company_id", "start_date"),
#     )
#
#     def __repr__(self) -> str:
#         return f"<ItemWarranty id={self.id} item={self.item_id} start={self.start_date} dur={self.duration_months}m>"
#
#
# class ItemWarrantyPolicy(BaseModel):
#     """
#     Optional default template per item. This is the master data table.
#     The service layer uses this to pre-fill ItemWarranty records automatically.
#     This keeps the process simple for end users.
#     """
#     __tablename__ = "item_warranty_policies"
#
#     company_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("companies.id", ondelete="CASCADE"),
#                                             nullable=False, index=True)
#     item_id:    Mapped[int] = mapped_column(db.BigInteger, ForeignKey("items.id", ondelete="CASCADE"),
#                                             nullable=False, unique=True, index=True)
#
#     default_duration_months: Mapped[int] = mapped_column(db.Integer, nullable=False, default=12)
#
#     item: Mapped["Item"] = relationship("Item", backref="warranty_policy", lazy="select")
#
#     __table_args__ = (
#         CheckConstraint("default_duration_months >= 0", name="ck_policy_duration_nonneg"),
#         Index("ix_item_warranty_policy_company_item", "company_id", "item_id"),
#     )
#
#     def __repr__(self) -> str:
#         return f"<ItemWarrantyPolicy item={self.item_id} months={self.default_duration_months}>"
#
#
# class InventoryAlertRule(BaseModel):
#     """
#     Simple, flexible alert rules.
#     You can scope by item OR brand OR branch (all optional). Service uses what’s set.
#     """
#     __tablename__ = "inventory_alert_rules"
#
#     company_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("companies.id", ondelete="CASCADE"),
#                                             nullable=False, index=True)
#     event_type: Mapped[InventoryEventTypeEnum] = mapped_column(
#         db.Enum(InventoryEventTypeEnum), nullable=False, index=True
#     )
#
#     # Optional scope knobs — set only what you need.
#     branch_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, ForeignKey("branches.id", ondelete="CASCADE"),
#                                                      nullable=True, index=True)
#     item_id:   Mapped[Optional[int]] = mapped_column(db.BigInteger, ForeignKey("items.id", ondelete="CASCADE"),
#                                                      nullable=True, index=True)
#     brand_id:  Mapped[Optional[int]] = mapped_column(db.BigInteger, ForeignKey("brands.id", ondelete="CASCADE"),
#                                                      nullable=True, index=True)
#
#     advance_days: Mapped[int] = mapped_column(db.Integer, nullable=False, default=30)
#     is_active:    Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)
#
#     __table_args__ = (
#         CheckConstraint("advance_days >= 0", name="ck_alert_advance_nonneg"),
#         UniqueConstraint("company_id", "event_type", "branch_id", "item_id", "brand_id",
#                          name="uq_alert_scope"),
#         Index("ix_alert_rules_company_event_active", "company_id", "event_type", "is_active"),
#     )
#
#     def __repr__(self) -> str:
#         return f"<InventoryAlertRule company={self.company_id} type={self.event_type} days={self.advance_days}>"
