"""
Sync script: Read Google Sheet via GCP Service Account
- Extract all 'yes' entries into sent_log.json
- Delete all 'no' entries from the sheet
- Remove empty rows (where Domain is blank)
"""
import json
import os
from datetime import datetime

CREDENTIALS_PATH = "gen-lang-client-0428625036-fcdde7565288.json"
SENT_LOG = "sent_log.json"

SHEET_ID = "1-AUFpWgfJyuQLI3NxdE6mPtgl93-N87st4Emk0aGieY"


def main():
    import gspread
    from google.oauth2.service_account import Credentials

    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scope)
    client = gspread.authorize(creds)

    print(f"Opening sheet {SHEET_ID}...")
    sh = client.open_by_key(SHEET_ID)
    sheet = sh.sheet1

    print(f"Reading all rows from sheet '{sheet.title}'...")
    values = sheet.get_values()
    if not values:
        print("Sheet is empty!")
        return

    # First row = header
    header = values[0]
    # Print header for debugging
    print(f"Header: {header}")
    print(f"Total rows (including header): {len(values)}")

    yes_entries = []   # Will go into sent_log.json
    no_rows_to_delete = []  # Row numbers (1-indexed) to delete

    for i, row in enumerate(values[1:], start=2):
        # Columns: A=Domain, B=Company, C=Email, D=Sent At, E=Status
        domain = (row[0] or "").strip().lower() if len(row) > 0 else ""
        company = (row[1] or "").strip() if len(row) > 1 else ""
        email = (row[2] or "").strip().lower() if len(row) > 2 else ""
        sent_at = (row[3] or "").strip() if len(row) > 3 else ""
        status = (row[4] or "").strip().lower() if len(row) > 4 else ""

        # Skip empty rows (no domain)
        if not domain:
            continue

        if status == "yes":
            # Normalize sent_at timestamp
            if sent_at and "/" in sent_at:
                # Google Sheets may return datetime objects as strings like "2026-04-01 17:07:30"
                # Try to reformat if needed
                pass

            yes_entries.append({
                "domain": domain,
                "company": company,
                "email": email,
                "sent_at": sent_at,
            })
        elif status == "no":
            no_rows_to_delete.append(i)
        else:
            print(f"  Row {i}: domain={domain}, status='{status}' -> skipping")

    print(f"\nFound {len(yes_entries)} 'yes' entries, {len(no_rows_to_delete)} 'no' rows to delete")

    # Build sent_log.json from 'yes' entries
    sent_log = {}
    for entry in yes_entries:
        sent_log[entry["domain"]] = {
            "email": entry["email"],
            "sent_at": entry["sent_at"],
        }

    # Save sent_log.json
    with open(SENT_LOG, "w") as f:
        json.dump(sent_log, f, indent=2)
    print(f"\nWrote {len(sent_log)} entries to {SENT_LOG}")

    # Delete 'no' rows from sheet (reverse order to preserve row indices)
    if no_rows_to_delete:
        print(f"\nDeleting {len(no_rows_to_delete)} 'no' rows from sheet...")
        for row_num in reversed(no_rows_to_delete):
            sheet.delete_rows(row_num)
        print("Done deleting 'no' entries from sheet.")
    else:
        print("No 'no' entries to delete.")

    # Also remove any empty rows from sheet
    # Read again to find empty domain rows
    values_after = sheet.get_values()
    empty_rows = []
    for i, row in enumerate(values_after[1:], start=2):
        if not (row[0] or "").strip():
            empty_rows.append(i)

    if empty_rows:
        print(f"\nCleaning up {len(empty_rows)} empty rows...")
        for row_num in reversed(empty_rows):
            sheet.delete_rows(row_num)
        print("Done.")

    print(f"\n✅ Sync complete! sent_log.json has {len(sent_log)} companies.")


if __name__ == "__main__":
    main()
