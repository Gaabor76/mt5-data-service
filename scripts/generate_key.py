"""Generate a Fernet encryption key for broker credential storage."""

from cryptography.fernet import Fernet

key = Fernet.generate_key().decode()
print(f"\nGenerated encryption key:\n\n  {key}\n")
print("Copy this into your .env file as ENCRYPTION_KEY=")
