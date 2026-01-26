import sys
import os
sys.path.append(os.getcwd())
from app import create_app
from config.database import db
from sqlalchemy import text

def debug_supplier_gl(supplier_name="Tijaabo"):
    app = create_app()
    with app.app_context():
        # 1. Find Party ID
        sql_party = "SELECT id, name FROM parties WHERE name = :name"
        party = db.session.execute(text(sql_party), {"name": supplier_name}).fetchone()
        
        if not party:
            print(f"Party '{supplier_name}' not found.")
            return

        print(f"--- GL Entries for {supplier_name} (ID: {party.id}) ---")
        
        # 2. Get GL Entries
        sql_gl = """
            SELECT 
                gle.id, 
                gle.posting_date, 
                gle.credit, 
                gle.debit, 
                gle.journal_entry_id, 
                je.code as je_code,
                doc_types.label as source_doc_type,
                gle.source_doc_id
            FROM general_ledger_entries gle
            LEFT JOIN journal_entries je ON je.id = gle.journal_entry_id
            LEFT JOIN document_types doc_types ON doc_types.id = gle.source_doctype_id
            WHERE gle.party_id = :pid
            ORDER BY gle.posting_date, gle.id
        """
        
        rows = db.session.execute(text(sql_gl), {"pid": party.id}).mappings().all()
        
        for r in rows:
            print(f"ID: {r.id} | Date: {r.posting_date} | Dr: {r.debit} | Cr: {r.credit} | JE: {r.je_code} ({r.journal_entry_id}) | Source: {r.source_doc_type} #{r.source_doc_id}")

if __name__ == "__main__":
    debug_supplier_gl()
