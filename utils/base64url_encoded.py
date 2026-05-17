"""
Generate a cryptographically secure 256-bit (32-byte) API key encoded as
base64url (RFC 4648 §5) without padding, suitable for use as an X-API-Key
token or APP_AUTHORIZED_TOKENS value in .env.
"""

import base64
import secrets
import sys


def generate_key() -> str:
    """Return a 43-character base64url-encoded 256-bit random key."""
    raw = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> None:
    key = generate_key()

    out = sys.stdout.write
    sep = "=" * 60

    out(f"{sep}\n")
    out("Generated 256-bit API Key (base64url encoded)\n")
    out(f"{sep}\n")
    out(f"\nKey:  {key}\n")
    out("\nAdd this to your .env file:\n")
    out(f"\n  APP_AUTHORIZED_TOKENS={key}\n")
    out("\nUse in HTTP requests:\n")
    out(f"\n  X-API-Key: {key}\n")
    out(f"  Authorization: Bearer {key}\n")
    out(f"\n{sep}\n")
    out("IMPORTANT: Keep this key secret. Do not commit to version control.\n")
    out(f"{sep}\n")


if __name__ == "__main__":
    main()
