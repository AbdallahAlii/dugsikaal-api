from __future__ import annotations

import logging
from typing import Dict, Any
from sqlalchemy.orm import Session

from app.seed_data.coa.seeder import seed_chart_of_accounts
from app.seed_data.gl_templates.seeder import seed_gl_templates
from app.seed_data.core_org.seeder import seed_core_org_masters
from app.seed_data.core_org.seeder import seed_company_fiscal_and_hr_defaults
from app.seed_data.education_defaults.seeder import seed_education_defaults
from app.seed_data.education_fees_defaults.seeder import seed_education_fees_billing_defaults

log = logging.getLogger("company.bootstrap")


class CompanyBootstrapper:
    """
    ERPNext / Odoo style company provisioning orchestrator.
    - STRICT order
    - Atomic (no commits here)
    - Shared registry for cross-step dependencies
    """

    def __init__(self, db: Session, company_id: int):
        self.db = db
        self.company_id = company_id
        self.registry: Dict[str, Any] = {}

    # -------------------------------------------------
    # Public entry
    # -------------------------------------------------

    def run(self) -> None:
        log.info("🚀 [BOOTSTRAP] Start provisioning company_id=%s", self.company_id)

        self._step("1. Chart of Accounts", self._seed_coa)
        self._step("2. GL Templates", self._seed_gl)
        self._step("3. Core Org Masters", self._seed_core_org)
        self._step("4. Fiscal & HR Defaults", self._seed_fiscal_hr)

        # 🔴 EDUCATION DEPENDENCY CHAIN
        self._step("5. Education Core", self._seed_education)
        self._step("6. Education Fee Billing", self._seed_fees)

        log.info("✅ [BOOTSTRAP] Company provisioned company_id=%s", self.company_id)

    # -------------------------------------------------
    # Internal helpers
    # -------------------------------------------------
    def _step(self, label: str, fn) -> None:
        log.info("👉 [BOOTSTRAP] %s", label)
        try:
            fn()
            self.db.flush()  # sync but do not commit
        except Exception as e:
            log.exception("❌ [BOOTSTRAP] FAILED at %s", label)
            raise

    # -------------------------------------------------
    # Steps
    # -------------------------------------------------
    def _seed_coa(self):
        seed_chart_of_accounts(
            self.db,
            company_id=self.company_id,
            root_code=None,
            root_name="Root Chart of Accounts",
            use_company_prefix_for_root=True,
            set_status_submitted=True,
            create_balances_for_leaves=True,
        )

    def _seed_gl(self):
        seed_gl_templates(self.db, company_id=self.company_id)

    def _seed_core_org(self):
        seed_core_org_masters(self.db, company_id=self.company_id)

    def _seed_fiscal_hr(self):
        seed_company_fiscal_and_hr_defaults(self.db, company_id=self.company_id)

    def _seed_education(self):
        """
        Seeds:
        - ONE Academic Year (current only)
        - Programs (Grade 1–12)
        - Courses, Sessions
        - Student Groups
        Stores program_ids + academic_year_id in registry
        """
        ctx = seed_education_defaults(self.db, company_id=self.company_id)
        self.registry.update(ctx)

    def _seed_fees(self):
        """
        Uses registry from education_defaults (no re-querying).
        """
        seed_education_fees_billing_defaults(
            self.db,
            company_id=self.company_id,
            context=self.registry,
        )
