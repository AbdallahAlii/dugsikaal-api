# app/auth/me_repository.py
from __future__ import annotations
from typing import Optional, Dict, Any, List
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import joinedload, selectinload

from app.application_hr.models.hr import Employee, EmployeeAssignment
from app.application_rbac.rbac_models import Role, UserRole
from app.application_org.models.company import Branch
from config.database import db
from app.auth.models.users import User, UserAffiliation


class ProfileRepo:
    def fetch_core(self, *, user_id: int, company_id: int, branch_id: Optional[int]) -> Optional[Dict[str, Any]]:
        # Active affiliation for this scope (prefer exact match; else primary in this company; else any in company)
        aff_q = (
            select(UserAffiliation)
            .options(
                joinedload(UserAffiliation.user)
                    .joinedload(User.employee)
                    .options(selectinload(Employee.assignments)),
                joinedload(UserAffiliation.company),
                joinedload(UserAffiliation.branch),
            )
            .where(
                UserAffiliation.user_id == user_id,
                UserAffiliation.company_id == company_id,
            )
        )
        affs = db.session.execute(aff_q).scalars().all()
        if not affs:
            return None

        active = None
        if branch_id:
            active = next((a for a in affs if a.branch_id == branch_id), None)
        if not active:
            active = next((a for a in affs if a.is_primary), None)
        if not active:
            active = affs[0]

        user = active.user
        company = active.company
        affiliation_branch = active.branch

        # Employee & primary assignment (may be in a different branch)
        employee: Optional[Employee] = getattr(user, "employee", None)
        pa: Optional[EmployeeAssignment] = employee.primary_assignment if employee else None

        # Resolve “display branch” (assignment branch > affiliation branch) within same company
        display_branch: Optional[Branch] = None
        if pa and pa.company_id == company.id:
            display_branch = pa.branch
        elif affiliation_branch:
            display_branch = affiliation_branch

        # Role names for current scope (SYSTEM/global or matching company/branch)
        # SYSTEM/global UserRole rows often have company_id/branch_id NULL
        role_q = (
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                UserRole.is_active == True,
                # current context: allow system/global (NULL) + current company + branch
                and_(
                    or_(UserRole.company_id == None, UserRole.company_id == company.id),
                    or_(UserRole.branch_id == None, display_branch is None, UserRole.branch_id == (display_branch.id if display_branch else None)),
                ),
            )
        )
        role_names = [r[0] for r in db.session.execute(role_q).all()]

        return {
            "user": {
                "id": user.id,
                "username": user.username,
                "full_name": (employee.full_name if employee else None) or user.username,
                "avatar_img_key": employee.img_key if employee and employee.img_key else None,
            },
            "company": {
                "id": company.id,
                "name": company.name,
                "img_key": company.img_key,
            },
            "branch": {
                "id": display_branch.id,
                "name": display_branch.name,
                "img_key": display_branch.img_key,
            } if display_branch else None,
            "aff_scope": {"company_id": company.id, "branch_id": display_branch.id if display_branch else None},
            "job_title": pa.job_title if pa else None,
            "roles": role_names,
        }

profile_repo = ProfileRepo()
