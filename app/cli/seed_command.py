# app/commands/seed_command.py
from __future__ import annotations

from typing import List

import click
import logging
from flask.cli import with_appcontext

from app.seed_data.coa.seeder import seed_chart_of_accounts
from app.seed_data.codes.seeder import seed_code_types
from app.seed_data.core.seeder import seed_initial_organization
from app.seed_data.doctypes.seeder import seed_document_types
from app.seed_data.gl_templates.seeder import seed_gl_templates
from app.seed_data.navigation_workspace.seeder import seed_navigation_workspaces
# Your Flask-SQLAlchemy db
from config.database import db

# Import your seeders (RBAC for now). Keep a fallback import to reduce path headaches.
try:
    from app.seed_data.rbac.seeder import seed_rbac
except ImportError:
    # If you placed it under project_root/seed_data/rbac/seeder.py
    from seed_data.rbac.seeder import seed_rbac  # type: ignore

logger = logging.getLogger(__name__)


@click.group(name="seed")
def seed_cli():
    """Database seeding commands."""
    # nothing to do here; subcommands will run under app context
    pass
@seed_cli.command("doctypes")  # ← NEW command
@with_appcontext
def seed_doctypes_only():
    """Run only the DocumentType seeder."""
    try:
        click.echo("🌱 Seeding Document Types...")
        seed_document_types(db.session)
        db.session.commit()
        click.secho("✅ Document Types seeded successfully!", fg="green")
    except Exception as e:
        db.session.rollback()
        logger.error("Document Types seeding failed", exc_info=True)
        click.secho(f"❌ Error seeding Document Types: {e}", fg="red")
        raise SystemExit(1)

@seed_cli.command("all")
@with_appcontext
def seed_all():
    """
    Run all seeders in the correct order.
    Extend this as you add more seeders (geo, core, etc).
    """
    try:
        click.echo("🚀 Starting full database seeding...")

        # Call seeders in dependency order.
        # Seeders are called in dependency order:
        # Core data (users, companies) must exist before RBAC roles can be assigned.

        click.echo("🏢 Seeding initial organization (companies, branches, departments, owners)...")
        seed_initial_organization(db.session)
        click.echo("🔐 Seeding RBAC...")
        seed_rbac(db.session)

        # --- NEW COA SEEDING ---
        click.echo("💰 Seeding Chart of Accounts for specified companies...")
        seed_chart_of_accounts(db.session, company_id=22)
        seed_chart_of_accounts(db.session, company_id=5)
        # seed_initial_organization(db.session)

        db.session.commit()
        click.secho("✅ All data seeded successfully!", fg="green")
    except Exception as e:
        db.session.rollback()
        logger.error("Seeding failed", exc_info=True)
        click.secho(f"❌ Seeding failed: {e}", fg="red")
        raise SystemExit(1)

@seed_cli.command("core")
@with_appcontext
def seed_core_only():
    """Run only the core organization seeder."""
    try:
        click.echo("🌱 Seeding core organization data...")
        seed_initial_organization(db.session)
        db.session.commit()
        click.secho("✅ Core data seeded successfully!", fg="green")
    except Exception as e:
        db.session.rollback()
        logger.error("Core seeding failed", exc_info=True)
        click.secho(f"❌ Error seeding core data: {e}", fg="red")
        raise SystemExit(1)


@seed_cli.command("rbac")
@with_appcontext
def seed_rbac_only():
    """Run only the RBAC seeder."""
    try:
        click.echo("🌱 Seeding RBAC data...")
        seed_rbac(db.session)
        db.session.commit()
        click.secho("✅ RBAC data seeded successfully!", fg="green")
    except Exception as e:
        db.session.rollback()
        logger.error("RBAC seeding failed", exc_info=True)
        click.secho(f"❌ Error seeding RBAC: {e}", fg="red")
        raise SystemExit(1)


@seed_cli.command("codes") # Added this new command
@with_appcontext
def seed_codes_only():
    """Run only the code types seeder."""
    try:
        click.echo("🌱 Seeding code types data...")
        seed_code_types(db.session)
        db.session.commit()
        click.secho("✅ Code types data seeded successfully!", fg="green")
    except Exception as e:
        db.session.rollback()
        logger.error("Code types seeding failed", exc_info=True)
        click.secho(f"❌ Error seeding code types: {e}", fg="red")
        raise SystemExit(1)



@seed_cli.command("coa")
@with_appcontext
@click.option("--company", "company_ids", multiple=True, type=int,
              help="Company IDs to seed COA for (can be repeated). If omitted, uses 22 and 5.")
@click.option("--no-prefix-root", is_flag=True, default=False,
              help="Use 'COA' as root instead of '{PREFIX}-COA'.")
def seed_coa_only(company_ids: tuple[int, ...], no_prefix_root: bool):
    """Run only the Chart of Accounts seeder."""
    try:
        ids = list(company_ids) or [1]
        click.echo(f"🌱 Seeding Chart of Accounts for: {ids}")
        for cid in ids:
            seed_chart_of_accounts(
                db.session,
                company_id=cid,
                use_company_prefix_for_root=not no_prefix_root,
                set_status_submitted=True,
                create_balances_for_leaves=True,
            )
        db.session.commit()
        click.secho("✅ Chart of Accounts seeded successfully!", fg="green")
    except Exception as e:
        db.session.rollback()
        logger.error("COA seeding failed", exc_info=True)
        click.secho(f"❌ Error seeding Chart of Accounts: {e}", fg="red")
        raise SystemExit(1)





def _parse_company_ids(arg: str | None, *, default_ids: List[int]) -> List[int]:
    if not arg:
        return default_ids
    parts = [p.strip() for p in arg.split(",") if p.strip()]
    out: List[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            raise click.BadParameter(f"Invalid company id {p!r}. Use comma-separated integers.")
    if not out:
        return default_ids
    return out






@seed_cli.command("gl-templates")
@click.option(
    "--company-ids",
    help="Comma-separated company IDs (default: 22,5)",
    default=None,
)
@with_appcontext
def seed_gl_only(company_ids: str | None):
    """
    Run only the GL Entry Templates seeder for specified companies.
    Make sure COA and Document Types are already seeded.
    """
    try:
        ids = _parse_company_ids(company_ids, default_ids=[22, 5])

        click.echo("📘 Seeding GL Entry Templates...")
        for cid in ids:
            seed_gl_templates(db.session, company_id=cid)

        db.session.commit()
        click.secho("✅ GL Entry Templates seeded successfully!", fg="green")
    except Exception as e:
        db.session.rollback()
        logger.error("GL template seeding failed", exc_info=True)
        click.secho(f"❌ Error seeding GL Entry Templates: {e}", fg="red")
        raise SystemExit(1)



@seed_cli.command("nav")
@with_appcontext
def seed_nav_only():
    """Run only the navigation (workspaces + links) seeder."""
    from config.database import db
    import click, logging
    logger = logging.getLogger(__name__)
    try:
        click.echo("🌱 Seeding Navigation Workspaces...")
        seed_navigation_workspaces(db.session)
        db.session.commit()
        click.secho("✅ Navigation Workspaces seeded successfully!", fg="green")
    except Exception as e:
        db.session.rollback()
        logger.error("Navigation seeding failed", exc_info=True)
        click.secho(f"❌ Error seeding Navigation Workspaces: {e}", fg="red")
        raise SystemExit(1)
