# Auto-generated Supabase Schema Types
# DO NOT EDIT - Generated from live database extraction
# Source: Manual schema extraction from Supabase instance

from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel
from enum import Enum

# ====== AUTH SCHEMA ======

class AuthAuditLogEntry(BaseModel):
    """auth.audit_log_entries table model"""
    instance_id: Optional[UUID] = None
    id: UUID
    payload: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    ip_address: str = ""

class AuthFlowState(BaseModel):
    """auth.flow_state table model"""
    id: UUID
    user_id: Optional[UUID] = None
    auth_code: str
    code_challenge_method: str  # USER-DEFINED type
    code_challenge: str
    provider_type: str
    provider_access_token: Optional[str] = None
    provider_refresh_token: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    authentication_method: str
    auth_code_issued_at: Optional[datetime] = None

class AuthIdentity(BaseModel):
    """auth.identities table model"""
    id: UUID
    user_id: UUID
    identity_data: Dict[str, Any]
    provider: str
    provider_id: str
    email: Optional[str] = None
    last_sign_in_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class AuthInstance(BaseModel):
    """auth.instances table model"""
    id: UUID
    uuid: Optional[UUID] = None
    raw_base_config: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class AuthMfaAmrClaim(BaseModel):
    """auth.mfa_amr_claims table model"""
    id: UUID
    session_id: UUID
    authentication_method: str
    created_at: datetime
    updated_at: datetime

class AuthMfaChallenge(BaseModel):
    """auth.mfa_challenges table model"""
    id: UUID
    factor_id: UUID
    created_at: datetime
    verified_at: Optional[datetime] = None
    ip_address: str  # inet type
    otp_code: Optional[str] = None
    web_authn_session_data: Optional[Dict[str, Any]] = None

class AuthMfaFactor(BaseModel):
    """auth.mfa_factors table model"""
    id: UUID
    user_id: UUID
    friendly_name: Optional[str] = None
    factor_type: str  # USER-DEFINED type
    status: str  # USER-DEFINED type
    created_at: datetime
    updated_at: datetime
    secret: Optional[str] = None
    phone: Optional[str] = None
    last_challenged_at: Optional[datetime] = None
    web_authn_credential: Optional[Dict[str, Any]] = None
    web_authn_aaguid: Optional[UUID] = None

class AuthOneTimeToken(BaseModel):
    """auth.one_time_tokens table model"""
    id: UUID
    user_id: UUID
    token_type: str  # USER-DEFINED type
    token_hash: str
    relates_to: str
    created_at: datetime
    updated_at: datetime

class AuthRefreshToken(BaseModel):
    """auth.refresh_tokens table model"""
    id: int
    instance_id: Optional[UUID] = None
    token: Optional[str] = None
    user_id: Optional[str] = None
    revoked: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    parent: Optional[str] = None
    session_id: Optional[UUID] = None

class AuthSamlProvider(BaseModel):
    """auth.saml_providers table model"""
    id: UUID
    sso_provider_id: UUID
    entity_id: str
    metadata_xml: str
    metadata_url: Optional[str] = None
    attribute_mapping: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    name_id_format: Optional[str] = None

class AuthSamlRelayState(BaseModel):
    """auth.saml_relay_states table model"""
    id: UUID
    sso_provider_id: UUID
    request_id: str
    for_email: Optional[str] = None
    redirect_to: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    flow_state_id: Optional[UUID] = None

class AuthSchemaMigration(BaseModel):
    """auth.schema_migrations table model"""
    version: str

class AuthSession(BaseModel):
    """auth.sessions table model"""
    id: UUID
    user_id: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    factor_id: Optional[UUID] = None
    aal: Optional[str] = None  # USER-DEFINED type
    not_after: Optional[datetime] = None
    refreshed_at: Optional[datetime] = None
    user_agent: Optional[str] = None
    ip: Optional[str] = None  # inet type
    tag: Optional[str] = None

class AuthSsoDomain(BaseModel):
    """auth.sso_domains table model"""
    id: UUID
    sso_provider_id: UUID
    domain: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class AuthSsoProvider(BaseModel):
    """auth.sso_providers table model"""
    id: UUID
    resource_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class AuthUser(BaseModel):
    """auth.users table model - Core user record"""
    id: UUID
    instance_id: Optional[UUID] = None
    aud: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    encrypted_password: Optional[str] = None
    invited_at: Optional[datetime] = None
    confirmation_token: Optional[str] = None
    confirmation_sent_at: Optional[datetime] = None
    recovery_token: Optional[str] = None
    recovery_sent_at: Optional[datetime] = None
    email_change: Optional[str] = None
    email_change_sent_at: Optional[datetime] = None
    last_sign_in_at: Optional[datetime] = None
    raw_app_meta_data: Optional[Dict[str, Any]] = None
    raw_user_meta_data: Optional[Dict[str, Any]] = None
    is_super_admin: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    email_change_token_new: Optional[str] = None
    phone_confirmed_at: Optional[datetime] = None
    phone_change_sent_at: Optional[datetime] = None
    email_confirmed_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    phone_change_token: Optional[str] = ""
    phone: Optional[str] = None
    phone_change: Optional[str] = ""
    email_change_token_current: Optional[str] = ""
    email_change_confirm_status: Optional[int] = 0
    banned_until: Optional[datetime] = None
    reauthentication_token: Optional[str] = ""
    reauthentication_sent_at: Optional[datetime] = None
    is_sso_user: bool = False
    deleted_at: Optional[datetime] = None
    is_anonymous: bool = False

# ====== STORAGE SCHEMA ======

class StorageBucket(BaseModel):
    """storage.buckets table model"""
    id: str
    name: str
    owner: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    allowed_mime_types: Optional[List[str]] = None
    public: bool = False
    avif_autodetection: bool = False
    file_size_limit: Optional[int] = None
    owner_id: Optional[str] = None

class StorageMigration(BaseModel):
    """storage.migrations table model"""
    id: int
    name: str
    hash: str
    executed_at: Optional[datetime] = None

class StorageObject(BaseModel):
    """storage.objects table model"""
    id: UUID
    bucket_id: Optional[str] = None
    name: Optional[str] = None
    owner: Optional[UUID] = None
    created_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None
    updated_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    path_tokens: Optional[List[str]] = None
    version: Optional[str] = None
    owner_id: Optional[str] = None
    user_metadata: Optional[Dict[str, Any]] = None

class StorageS3MultipartUpload(BaseModel):
    """storage.s3_multipart_uploads table model"""
    id: str
    upload_signature: str
    bucket_id: str
    key: str
    version: str
    owner_id: Optional[str] = None
    created_at: datetime
    in_progress_size: int = 0
    user_metadata: Optional[Dict[str, Any]] = None

class StorageS3MultipartUploadPart(BaseModel):
    """storage.s3_multipart_uploads_parts table model"""
    id: UUID
    upload_id: str
    part_number: int
    bucket_id: str
    key: str
    size: int = 0
    etag: str
    owner_id: Optional[str] = None
    version: str
    created_at: datetime

# ====== REALTIME SCHEMA ======

class RealtimeMessage(BaseModel):
    """realtime.messages table model"""
    id: UUID
    topic: str
    extension: str
    payload: Optional[Dict[str, Any]] = None
    event: Optional[str] = None
    private: bool = False
    updated_at: datetime
    inserted_at: datetime

class RealtimeSchemaMigration(BaseModel):
    """realtime.schema_migrations table model"""
    version: int
    inserted_at: Optional[datetime] = None

class RealtimeSubscription(BaseModel):
    """realtime.subscription table model"""
    id: int
    entity: str  # regclass type
    filters: List[Any] = []  # ARRAY of user_defined_filter
    subscription_id: UUID
    claims: Dict[str, Any]
    claims_role: str  # regrole type
    created_at: datetime

# ====== VAULT SCHEMA ======

class VaultSecret(BaseModel):
    """vault.secrets table model"""
    id: UUID
    name: Optional[str] = None
    secret: str
    key_id: Optional[UUID] = None
    description: str = ""
    nonce: Optional[bytes] = None
    created_at: datetime
    updated_at: datetime

# ====== SUPABASE MIGRATIONS SCHEMA ======

class SupabaseMigrationSchemaMigration(BaseModel):
    """supabase_migrations.schema_migrations table model"""
    version: str
    statements: Optional[List[str]] = None
    name: Optional[str] = None

class SupabaseMigrationSeedFile(BaseModel):
    """supabase_migrations.seed_files table model"""
    path: str
    hash: str

# ====== HELPER FUNCTIONS FOR RLS ======

# These are PostgreSQL functions available in Supabase
# auth.uid() -> UUID | None
# auth.role() -> str  # 'authenticated', 'anon', 'service_role'

# ====== TYPE UNIONS FOR COMMON USE CASES ======

# User-related types
UserRelatedType = Union[AuthUser, AuthSession, AuthIdentity]

# Storage-related types  
StorageRelatedType = Union[StorageBucket, StorageObject, StorageS3MultipartUpload]

# Auth session and token types
AuthTokenType = Union[AuthRefreshToken, AuthOneTimeToken, AuthSession]