"""
OAuth Setup Script for Gmail

This script handles the OAuth flow to get tokens for the Gmail API.
Run this on your laptop (where you have a browser) to authorize the application.

Usage:
    python setup_oauth.py

Requirements:
    - GOOGLE_CLIENT_ID environment variable
    - GOOGLE_CLIENT_SECRET environment variable
    - A browser to complete the OAuth flow

The script will create/update token.json with credentials for the Gmail API.
"""

import json
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

# Scopes needed by this email agent server
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",  # List, read emails
    "https://www.googleapis.com/auth/gmail.modify",    # Mark read, label, archive
]

TOKEN_FILE = "token.json"


def main():
    # Check for required environment variables
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Error: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set")
        print("\nTo set them:")
        print("  export GOOGLE_CLIENT_ID='your-client-id'")
        print("  export GOOGLE_CLIENT_SECRET='your-client-secret'")
        print("\nYou can get these from the Google Cloud Console:")
        print("  https://console.cloud.google.com/apis/credentials")
        return 1

    # Build the client config (normally this comes from a downloaded JSON file,
    # but we construct it from environment variables for flexibility)
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    print("=" * 60)
    print("Google OAuth Setup for Gmail")
    print("=" * 60)
    print(f"\nRequesting scopes:")
    for scope in SCOPES:
        print(f"  - {scope.split('/')[-1]}")
    print()

    # Check if token already exists
    if Path(TOKEN_FILE).exists():
        with open(TOKEN_FILE) as f:
            existing = json.load(f)
        existing_scopes = set(existing.get("scopes", []))
        needed_scopes = set(SCOPES)

        if needed_scopes.issubset(existing_scopes):
            print(f"✓ {TOKEN_FILE} already has all required scopes.")
            print("  No action needed. Delete token.json to force re-authorization.")
            return 0
        else:
            missing = needed_scopes - existing_scopes
            print(f"Existing token is missing scopes: {missing}")
            print("Re-authorization required.\n")

    # Run the OAuth flow
    print("Opening browser for authorization...")
    print("(If browser doesn't open, check the terminal for a URL)\n")

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    # run_local_server opens a browser and handles the callback
    credentials = flow.run_local_server(port=0)

    # Save the credentials
    with open(TOKEN_FILE, "w") as f:
        f.write(credentials.to_json())

    print()
    print("=" * 60)
    print(f"✓ Authorization successful! Token saved to {TOKEN_FILE}")
    print("=" * 60)
    print(f"\nScopes authorized:")
    for scope in credentials.scopes:
        print(f"  - {scope.split('/')[-1]}")

    return 0


if __name__ == "__main__":
    exit(main())
