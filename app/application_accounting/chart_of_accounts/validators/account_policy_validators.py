from __future__ import annotations
from app.business_validation.item_validation import BizValidationError

class ModeOfPaymentValidator:
    @staticmethod
    def validate_name(name: str):
        if not name or not name.strip():
            raise BizValidationError("Name is required")

class AccountAccessPolicyValidator:
    @staticmethod
    def ensure_leaf(is_leaf: bool):
        if not is_leaf:
            raise BizValidationError("Account must be a leaf account")

    @staticmethod
    def ensure_account_linked(linked: bool):
        if not linked:
            raise BizValidationError("Account not linked to Mode of Payment")