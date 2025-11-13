# application_data_import/cli/import_cli.py
from __future__ import annotations
import click
from pathlib import Path

from config.database import db
from ..models import DataImport, ImportType, FileType, ImportStatus
from ..services.import_service import create_data_import_record, attach_import_file_encrypted, start_import_job


@click.group()
def di():
    """Data Import CLI"""
    pass


@di.command("run")
@click.option("--doctype", required=True)
@click.option("--company-id", required=True, type=int)
@click.option("--branch-id", default=None, type=int)
@click.option("--user-id", required=True, type=int)
@click.option("--type", "imp_type", required=True, type=click.Choice(["Insert", "Update"]))
@click.option("--file", "file_path", required=True, type=click.Path(exists=True))
def run_import(doctype: str, company_id: int, branch_id: int | None, user_id: int, imp_type: str, file_path: str):
    ft = FileType.EXCEL if Path(file_path).suffix.lower() in (".xlsx", ".xls") else FileType.CSV
    di = create_data_import_record(
        company_id=company_id,
        branch_id=branch_id,
        created_by_id=user_id,
        reference_doctype=doctype,
        import_type=ImportType(imp_type),
        file_type=ft,
        mute_emails=True,
    )
    with open(file_path, "rb") as f:
        attach_import_file_encrypted(di, f.read(), Path(file_path).name)
    db.session.commit()

    job_id = start_import_job(di.id)
    click.echo(f"Enqueued DI#{di.id} job={job_id or 'inline'}")
