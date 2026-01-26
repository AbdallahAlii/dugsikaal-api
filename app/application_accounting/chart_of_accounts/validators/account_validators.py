from __future__ import annotations
import re
from typing import Optional, List
import logging

from app.application_accounting.chart_of_accounts.models import (
    Account,
    AccountTypeEnum,
    ReportTypeEnum,
)
from app.business_validation.item_validation import BizValidationError

log = logging.getLogger(__name__)

ERR_ACCOUNT_EXISTS = "Account Number {code} is already used by account '{name}'."
ERR_INVALID_CODE_FORMAT = "Invalid account number format. Use 4 digits or 4 digits + dash + 2 digits (e.g. 1152 or 1152-01)."
ERR_INVALID_CODE_PREFIX = "Invalid account number: {atype} accounts must start with digit '{digit}'."
ERR_PARENT_REQUIRED = "Parent account is required."
ERR_PARENT_NOT_GROUP = "Parent account must be a group account."
ERR_TYPE_MISMATCH_PARENT = "Account type must match the parent account type."
ERR_ROOT_ACCOUNT_DELETE = "Root accounts cannot be deleted."
ERR_GROUP_HAS_CHILDREN = "Cannot delete group account that has child accounts."
ERR_ACCOUNT_HAS_TRANSACTIONS = "Account with existing transaction can not be deleted."
ERR_ACCOUNT_TYPE_CHANGE_NOT_ALLOWED = "Cannot change account type or report type for accounts with existing transactions."
ERR_PARENT_CHANGE_NOT_ALLOWED = "Cannot change parent account for accounts with existing transactions."
ERR_IS_GROUP_CHANGE_CHILDREN = "Cannot change group/leaf status while account has child accounts."
ERR_IS_GROUP_CHANGE_TRANSACTIONS = "Cannot change group/leaf status for accounts with existing transactions."

ERR_ACCOUNT_NAME_EXISTS = 'Account name "{name}" already exists.'

class AccountValidator:
    # 4 digits, optional "-NN"
    CODE_RE = re.compile(r"^[0-9]{4}(?:-[0-9]{2})?$")

    # Map first digit → AccountType
    PREFIX_MAP = {
        "1": AccountTypeEnum.ASSET,
        "2": AccountTypeEnum.LIABILITY,
        "3": AccountTypeEnum.EQUITY,
        "4": AccountTypeEnum.INCOME,
        "5": AccountTypeEnum.EXPENSE,
    }

    # Type → allowed 4-digit main range
    TYPE_RANGES = {
        AccountTypeEnum.ASSET: (1000, 1999),
        AccountTypeEnum.LIABILITY: (2000, 2999),
        AccountTypeEnum.EQUITY: (3000, 3999),
        AccountTypeEnum.INCOME: (4000, 4999),
        AccountTypeEnum.EXPENSE: (5000, 5999),
    }

    @classmethod
    def _digit_for_type(cls, account_type: AccountTypeEnum) -> str:
        for d, t in cls.PREFIX_MAP.items():
            if t == account_type:
                return d
        return "?"

    @classmethod
    def validate_code_format_and_prefix(cls, code: str, account_type: AccountTypeEnum) -> None:
        # Format
        if not cls.CODE_RE.match(code):
            raise BizValidationError(ERR_INVALID_CODE_FORMAT)

        # First digit vs AccountType
        first_digit = code[0]
        expected_type = cls.PREFIX_MAP.get(first_digit)
        if not expected_type or expected_type != account_type:
            raise BizValidationError(
                ERR_INVALID_CODE_PREFIX.format(
                    atype=account_type.value,
                    digit=cls._digit_for_type(account_type),
                )
            )

        # Range 1000–1999, 2000–2999, etc.
        main_part = code.split("-")[0]
        try:
            main_int = int(main_part)
        except ValueError:
            raise BizValidationError(ERR_INVALID_CODE_FORMAT)

        type_range = cls.TYPE_RANGES.get(account_type)
        if type_range:
            lo, hi = type_range
            if not (lo <= main_int <= hi):
                raise BizValidationError(
                    f"{account_type.value} account numbers must be between {lo} and {hi}."
                )

    @classmethod
    def validate_report_type(cls, account_type: AccountTypeEnum, report_type: ReportTypeEnum) -> None:
        if account_type in (AccountTypeEnum.ASSET, AccountTypeEnum.LIABILITY, AccountTypeEnum.EQUITY):
            if report_type != ReportTypeEnum.BALANCE_SHEET:
                raise BizValidationError("Balance Sheet accounts must use report type 'Balance Sheet'.")
        else:
            if report_type != ReportTypeEnum.PROFIT_AND_LOSS:
                raise BizValidationError("Income/Expense accounts must use report type 'Profit & Loss'.")

    @classmethod
    def validate_parent_on_create(cls, *, parent: Optional[Account], account_type: AccountTypeEnum) -> None:
        if parent is None:
            raise BizValidationError(ERR_PARENT_REQUIRED)
        if not parent.is_group:
            raise BizValidationError(ERR_PARENT_NOT_GROUP)
        if parent.account_type != account_type:
            raise BizValidationError(ERR_TYPE_MISMATCH_PARENT)

    # ---------- auto-code generation ----------

    @classmethod
    def generate_next_code(
        cls,
        *,
        parent: Account,
        existing_child_codes: List[str],
        account_type: AccountTypeEnum,
    ) -> str:
        """
        Generate the next account code under a parent.

        Cases:

        1) Parent is top-level pseudo root (e.g. 'NTS-COA', parent.parent_account_id is None):
           - Use type ranges:
             * ASSET   → 1000–1999
             * LIABILITY → 2000–2999
             * ...
           - Look at existing children in that range and pick max + 1.
           - If none exist, start at range low (e.g. 1000).

        2) Parent has numeric code, normal subtree:
           - If children look like '1152-01', '1152-02':
               → next '1152-03'
           - Else normal numeric children:
               parent '1110' -> children '1111', '1112', ...
        """
        raw_parent_code = (parent.code or "").strip()
        parent_code = raw_parent_code
        parent_main = parent_code.split("-")[0].strip()

        # Normalize existing child codes
        normalized_child_codes = [(c or "").strip() for c in existing_child_codes]

        # Get type range (for root-level numbering)
        type_range = cls.TYPE_RANGES.get(account_type)
        if not type_range:
            raise BizValidationError(f"Auto-numbering not configured for account type {account_type.value}.")
        lo, hi = type_range

        # Helper: collect numeric mains in this type's range for this parent
        mains_in_range: List[int] = []
        for c in normalized_child_codes:
            main = c.split("-")[0].strip()
            if main.isdigit():
                main_int = int(main)
                if lo <= main_int <= hi:
                    mains_in_range.append(main_int)

        # ---------- Case 1: pseudo-root like 'NTS-COA' ----------
        if parent.parent_account_id is None and not parent_main.isdigit():
            # This is your "NTS-COA" style root.
            if mains_in_range:
                next_main = max(mains_in_range) + 1
            else:
                next_main = lo  # e.g. 1000, 2000, 3000...

            code = f"{next_main:04d}"
            log.info(
                "generate_next_code: root parent.id=%s code=%r type=%s -> auto code=%s",
                parent.id,
                raw_parent_code,
                account_type.value,
                code,
            )
            cls.validate_code_format_and_prefix(code, account_type)
            return code

        # ---------- Case 2: normal numeric parent ----------
        if not parent_main.isdigit():
            # Non-numeric, non-root parent → we still treat as invalid
            log.error(
                "generate_next_code: parent.id=%s has invalid non-numeric code=%r (parent_main=%r)",
                parent.id,
                raw_parent_code,
                parent_main,
            )
            raise BizValidationError("Parent account has invalid code; cannot auto-generate account number.")

        try:
            parent_main_int = int(parent_main)
        except ValueError:
            log.error(
                "generate_next_code: int() failed for parent.id=%s code=%r",
                parent.id,
                raw_parent_code,
            )
            raise BizValidationError("Parent account has invalid code; cannot auto-generate account number.")

        # Detect party-style children, e.g. parent '1152' and children '1152-01', '1152-02'
        is_party_group = any(c.startswith(parent_code + "-") for c in normalized_child_codes)

        if is_party_group:
            suffixes: List[int] = []
            for c in normalized_child_codes:
                if c.startswith(parent_code + "-"):
                    suf = c[len(parent_code) + 1 :].strip()
                    if suf.isdigit():
                        suffixes.append(int(suf))
            next_suffix = (max(suffixes) if suffixes else 0) + 1
            code = f"{parent_code}-{next_suffix:02d}"
        else:
            mains: List[int] = []
            for c in normalized_child_codes:
                main = c.split("-")[0].strip()
                if main.isdigit():
                    mains.append(int(main))

            if mains:
                next_main = max(mains) + 1
            else:
                # First child under this parent
                next_main = parent_main_int + 1

            code = f"{next_main:04d}"

        # Final validation (format + prefix + range)
        cls.validate_code_format_and_prefix(code, account_type)
        return code

    # ---------- delete / update safety ----------

    @classmethod
    def ensure_deletable(
        cls,
        *,
        account: Account,
        has_children: bool,
        has_transactions: bool,
    ) -> None:
        if account.parent_account_id is None:
            raise BizValidationError(ERR_ROOT_ACCOUNT_DELETE)

        if has_children:
            raise BizValidationError(ERR_GROUP_HAS_CHILDREN)

        if has_transactions:
            raise BizValidationError(ERR_ACCOUNT_HAS_TRANSACTIONS)

    @classmethod
    def ensure_safe_update(
        cls,
        *,
        account: Account,
        updates: dict,
        has_transactions: bool,
        has_children: bool,
    ) -> None:
        if has_transactions:
            if any(k in updates for k in ("account_type", "report_type", "debit_or_credit")):
                raise BizValidationError(ERR_ACCOUNT_TYPE_CHANGE_NOT_ALLOWED)
            if "parent_account_id" in updates:
                raise BizValidationError(ERR_PARENT_CHANGE_NOT_ALLOWED)

        if "is_group" in updates:
            new_is_group = updates["is_group"]
            if has_children and new_is_group is False:
                raise BizValidationError(ERR_IS_GROUP_CHANGE_CHILDREN)
            if has_transactions and new_is_group is True:
                raise BizValidationError(ERR_IS_GROUP_CHANGE_TRANSACTIONS)