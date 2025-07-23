import os
from typing import Any, Dict, Optional
from supabase import create_client, Client

from app.config import settings
from app.core.exceptions import ValidationError, NotFoundError


class Database:
    """
    Wrapper around Supabase client to centralize DB access, encryption, and error mapping.
    """
    def __init__(self):
        # Initialize Supabase client with environment-backed settings
        self.client: Client = create_client(str(settings.database_url), settings.database_key)

    def table(self, name: str):
        """Get a reference to a table for CRUD operations."""
        return self.client.table(name)

    def rpc(self, fn: str, params: Dict[str, Any]):
        """Invoke a PostgreSQL function via RPC."""
        return self.client.rpc(fn, params)

    def encrypt(self, plaintext: str) -> bytes:
        """
        Encrypt a secret value using pgp_sym_encrypt via Supabase vault.
        Returns the encrypted bytes payload.
        """
        try:
            resp = (
                self.rpc("pgp_sym_encrypt", {"data": plaintext, "key": settings.vault_passphrase})
                .execute()
            )
            if resp.error:
                raise ValidationError(f"Encryption failed: {resp.error.message}")
            # RPC returns list-wrapped result
            return resp.data[0]
        except Exception as e:
            raise ValidationError(f"Encryption error: {str(e)}")

    def decrypt(self, ciphertext: bytes) -> str:
        """
        Decrypt a secret value using pgp_sym_decrypt via Supabase vault.
        Returns the original plaintext string.
        """
        try:
            resp = (
                self.rpc("pgp_sym_decrypt", {"data": ciphertext, "key": settings.vault_passphrase})
                .execute()
            )
            if resp.error:
                raise ValidationError(f"Decryption failed: {resp.error.message}")
            return resp.data[0]
        except Exception as e:
            raise ValidationError(f"Decryption error: {str(e)}")

    def execute(self, query: Any) -> Any:
        """
        Generic executor that raises on supabase errors.
        """
        result = query.execute()
        if result.error:
            raise Database._map_error(result.error)
        return result.data

    @staticmethod
    def _map_error(err: Any) -> Exception:
        """Map Supabase/PostgREST errors to application exceptions."""
        msg = err.message if hasattr(err, "message") else str(err)
        if "Not Found" in msg or "No Rows Found" in msg:
            return NotFoundError(msg)
        # Other mappings can be added here
        return Exception(msg)


# Singleton instance for import across repositories
db = Database()  
