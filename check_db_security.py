"""Script to check if sensitive data in database is encrypted."""

import asyncio
import sqlite3
from pathlib import Path


async def check_database_security():
    """Check if sensitive settings are encrypted in the database."""
    db_path = Path("data/cronator.db")

    if not db_path.exists():
        print("❌ Database not found")
        return

    print(f"🔍 Checking database: {db_path}\n")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if settings table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
    if not cursor.fetchone():
        print("⚠️  Settings table not found")
        conn.close()
        return

    # Get all settings
    cursor.execute("SELECT key, value FROM settings")
    settings = cursor.fetchall()

    print("📋 Settings in database:\n")

    sensitive_keys = {"smtp_password", "git_token"}
    encrypted_count = 0
    plaintext_count = 0

    for key, value in settings:
        is_sensitive = key in sensitive_keys

        # Check if value looks encrypted (Fernet produces base64 with specific patterns)
        is_encrypted = False
        if value and len(value) > 50 and not value.isalnum():
            # Fernet tokens start with 'gAAAAA' after base64 encoding
            is_encrypted = True

        status = "🔐" if is_encrypted else "📝"

        if is_sensitive:
            if is_encrypted:
                print(f"{status} {key:20s} = [ENCRYPTED] ✅")
                encrypted_count += 1
            else:
                print(f"{status} {key:20s} = {value[:50]}... ⚠️  SHOULD BE ENCRYPTED!")
                plaintext_count += 1
        else:
            print(f"{status} {key:20s} = {value[:50]}")

    conn.close()

    print("\n" + "=" * 60)
    print(f"🔐 Encrypted sensitive keys: {encrypted_count}")
    print(f"⚠️  Plaintext sensitive keys: {plaintext_count}")

    if plaintext_count > 0:
        print("\n❌ SECURITY ISSUE: Some sensitive data is not encrypted!")
        print("   Solution: Update settings via UI to re-save with encryption")
    elif encrypted_count > 0:
        print("\n✅ All sensitive data is properly encrypted!")
    else:
        print("\n✅ No sensitive data stored yet")


if __name__ == "__main__":
    asyncio.run(check_database_security())
