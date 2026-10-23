from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, create_engine, delete, select, update
from sqlalchemy.engine import URL
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


SERVER_MODE = os.getenv("ISC_EMAIL_GENERATOR_SERVER_MODE", "").strip() == "1"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SESSION_COOKIE = "isc_email_generator_session"
CSRF_COOKIE = "isc_email_generator_csrf"
SESSION_HOURS = 12


class ServerConfigurationError(RuntimeError):
    pass


class AuthenticationError(ValueError):
    pass


class ConcurrentUpdateError(ValueError):
    pass


class SecretUnavailableError(ValueError):
    pass


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="user")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ProjectState(Base):
    __tablename__ = "project_states"
    __table_args__ = (UniqueConstraint("owner_id", "project_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_key: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class StyleGuideState(Base):
    __tablename__ = "style_guides"
    __table_args__ = (UniqueConstraint("owner_id", "project_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_key: Mapped[str] = mapped_column(String(80))
    filename: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class EncryptedSecret(Base):
    __tablename__ = "encrypted_secrets"
    __table_args__ = (UniqueConstraint("owner_id", "scope", "secret_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # The system verifier uses a reserved owner and therefore this column is
    # deliberately not a foreign key. User ownership is enforced by every
    # accessor and covered by isolation tests.
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    scope: Mapped[str] = mapped_column(String(40))
    secret_key: Mapped[str] = mapped_column(String(160))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    project_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


_engine = None
SessionLocal = None
current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)
expected_project_version: ContextVar[int | None] = ContextVar("expected_project_version", default=None)
expected_style_guide_version: ContextVar[int | None] = ContextVar("expected_style_guide_version", default=None)
saved_project_version: ContextVar[int | None] = ContextVar("saved_project_version", default=None)
request_metadata: ContextVar[dict[str, Any] | None] = ContextVar("request_metadata", default=None)
_passwords = PasswordHasher()
_secrets_locked_reason = ""


def enabled() -> bool:
    return SERVER_MODE


def secrets_available() -> bool:
    return not bool(_secrets_locked_reason)


def initialize() -> None:
    global _engine, SessionLocal
    if not SERVER_MODE:
        return
    database_target: str | URL = DATABASE_URL
    if not database_target:
        required = {name: os.getenv(name, "").strip() for name in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")}
        if not all(required.values()):
            raise ServerConfigurationError("DATABASE_URL o las variables POSTGRES_HOST/DB/USER/PASSWORD son obligatorias en modo servidor.")
        database_target = URL.create(
            "postgresql+psycopg",
            username=required["POSTGRES_USER"],
            password=required["POSTGRES_PASSWORD"],
            host=required["POSTGRES_HOST"],
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=required["POSTGRES_DB"],
        )
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(database_target, pool_pre_ping=True)
    SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    with db_session() as db:
        if db.get(SchemaMigration, 1) is None:
            db.add(SchemaMigration(version=1))
            db.commit()
    try:
        _verify_master_key()
    except SecretUnavailableError as exc:
        # Authentication and non-secret data remain available so an operator
        # can diagnose/recover the key. Secret access stays fail-closed.
        global _secrets_locked_reason
        _secrets_locked_reason = str(exc)


def db_session():
    if SessionLocal is None:
        raise ServerConfigurationError("El almacenamiento de servidor no fue inicializado.")
    return SessionLocal()


def normalize_username(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized or len(normalized) > 120 or not all(char.isalnum() or char in "._-@" for char in normalized):
        raise AuthenticationError("El nombre de usuario no es válido.")
    return normalized


def password_hash(password: str) -> str:
    if len(password) < 12:
        raise AuthenticationError("La contraseña debe tener al menos 12 caracteres.")
    return _passwords.hash(password)


def create_user(username: str, password: str, role: str = "user", must_change: bool = True) -> dict[str, Any]:
    normalized = normalize_username(username)
    if role not in {"admin", "user"}:
        raise AuthenticationError("El rol no es válido.")
    with db_session() as db:
        if db.scalar(select(User).where(User.username == normalized)):
            raise AuthenticationError("El usuario ya existe.")
        user = User(id=str(uuid4()), username=normalized, password_hash=password_hash(password), role=role, must_change_password=must_change)
        db.add(user)
        db.commit()
        audit("user.created", {"target_user_id": user.id, "role": role}, actor_id=current_user_id.get())
        return public_user(user)


def public_user(user: User) -> dict[str, Any]:
    return {"id": user.id, "username": user.username, "role": user.role, "active": user.active, "must_change_password": user.must_change_password}


def authenticate(username: str, password: str) -> tuple[dict[str, Any], str, str]:
    normalized = normalize_username(username)
    now = datetime.now(timezone.utc)
    with db_session() as db:
        user = db.scalar(select(User).where(User.username == normalized))
        if not user or not user.active:
            raise AuthenticationError("Usuario o contraseña incorrectos.")
        locked_until = user.locked_until
        if locked_until and locked_until.replace(tzinfo=locked_until.tzinfo or timezone.utc) > now:
            raise AuthenticationError("La cuenta está temporalmente bloqueada por intentos fallidos.")
        try:
            _passwords.verify(user.password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            user.failed_attempts += 1
            if user.failed_attempts >= 5:
                user.locked_until = now + timedelta(minutes=15)
                user.failed_attempts = 0
            db.commit()
            audit("auth.failed", {"username": normalized}, actor_id=user.id)
            raise AuthenticationError("Usuario o contraseña incorrectos.")
        user.failed_attempts = 0
        user.locked_until = None
        raw_token = secrets.token_urlsafe(48)
        raw_csrf = secrets.token_urlsafe(32)
        db.add(LoginSession(id=str(uuid4()), user_id=user.id, token_hash=_digest(raw_token), csrf_hash=_digest(raw_csrf), expires_at=now + timedelta(hours=SESSION_HOURS)))
        db.commit()
        audit("auth.login", {}, actor_id=user.id)
        return public_user(user), raw_token, raw_csrf


def session_user(raw_token: str) -> dict[str, Any] | None:
    if not raw_token:
        return None
    now = datetime.now(timezone.utc)
    with db_session() as db:
        row = db.scalar(select(LoginSession).where(LoginSession.token_hash == _digest(raw_token)))
        if not row or row.expires_at.replace(tzinfo=row.expires_at.tzinfo or timezone.utc) <= now:
            return None
        user = db.get(User, row.user_id)
        return public_user(user) if user and user.active else None


def validate_csrf(raw_token: str, csrf: str) -> bool:
    with db_session() as db:
        row = db.scalar(select(LoginSession).where(LoginSession.token_hash == _digest(raw_token)))
        return bool(row and csrf and hmac.compare_digest(row.csrf_hash, _digest(csrf)))


def logout(raw_token: str) -> None:
    if not raw_token:
        return
    with db_session() as db:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == _digest(raw_token)))
        db.commit()


def invalidate_sessions(user_id: str) -> None:
    with db_session() as db:
        db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
        db.commit()


def change_password(user_id: str, current_password: str, new_password: str) -> None:
    with db_session() as db:
        user = db.get(User, user_id)
        if not user or not user.active:
            raise AuthenticationError("La cuenta no está disponible.")
        try:
            _passwords.verify(user.password_hash, current_password)
        except (VerifyMismatchError, InvalidHashError) as exc:
            raise AuthenticationError("La contraseña actual es incorrecta.") from exc
        user.password_hash = password_hash(new_password)
        user.must_change_password = False
        db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
        db.commit()
        audit("auth.password_changed", {}, actor_id=user_id)


def admin_list_users() -> list[dict[str, Any]]:
    with db_session() as db:
        return [public_user(user) for user in db.scalars(select(User).order_by(User.username)).all()]


def admin_reset_password(user_id: str, temporary_password: str) -> None:
    with db_session() as db:
        user = db.get(User, user_id)
        if not user:
            raise AuthenticationError("El usuario no existe.")
        user.password_hash = password_hash(temporary_password)
        user.must_change_password = True
        db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
        db.commit()
        audit("user.password_reset", {"target_user_id": user_id})


def admin_set_active(user_id: str, active: bool) -> None:
    with db_session() as db:
        user = db.get(User, user_id)
        if not user:
            raise AuthenticationError("El usuario no existe.")
        user.active = active
        if not active:
            db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
        db.commit()
        audit("user.activated" if active else "user.deactivated", {"target_user_id": user_id})


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fernet() -> Fernet:
    raw = os.getenv("ISC_EMAIL_GENERATOR_MASTER_KEY", "").strip()
    if not raw:
        raise SecretUnavailableError("Falta ISC_EMAIL_GENERATOR_MASTER_KEY; los secretos están bloqueados.")
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise SecretUnavailableError("La clave maestra no tiene un formato válido.") from exc


def _verify_master_key() -> None:
    global _secrets_locked_reason
    if not SERVER_MODE:
        return
    marker_key = "__master_key_verifier__"
    with db_session() as db:
        marker = db.scalar(select(EncryptedSecret).where(EncryptedSecret.owner_id == "__system__", EncryptedSecret.scope == "system", EncryptedSecret.secret_key == marker_key))
        cipher = _fernet()
        if marker is None:
            db.add(EncryptedSecret(id=str(uuid4()), owner_id="__system__", scope="system", secret_key=marker_key, ciphertext=cipher.encrypt(b"isc-email-generator-master-key-v1")))
            db.commit()
            _secrets_locked_reason = ""
            return
        try:
            clear = cipher.decrypt(marker.ciphertext)
        except InvalidToken as exc:
            _secrets_locked_reason = "La clave maestra no coincide con la utilizada para cifrar los secretos. No se modificó ningún dato."
            raise SecretUnavailableError(_secrets_locked_reason) from exc
        if clear != b"isc-email-generator-master-key-v1":
            _secrets_locked_reason = "El verificador de la clave maestra no es válido."
            raise SecretUnavailableError(_secrets_locked_reason)
        _secrets_locked_reason = ""


def _assert_secrets_unlocked() -> None:
    if _secrets_locked_reason:
        raise SecretUnavailableError(_secrets_locked_reason)


def set_secret(scope: str, key: str, value: str) -> None:
    _assert_secrets_unlocked()
    owner = require_user_id()
    cipher = _fernet()
    encrypted = cipher.encrypt(value.encode("utf-8"))
    with db_session() as db:
        row = db.scalar(select(EncryptedSecret).where(EncryptedSecret.owner_id == owner, EncryptedSecret.scope == scope, EncryptedSecret.secret_key == key))
        if row:
            row.ciphertext = encrypted
            row.updated_at = datetime.now(timezone.utc)
        else:
            db.add(EncryptedSecret(id=str(uuid4()), owner_id=owner, scope=scope, secret_key=key, ciphertext=encrypted))
        db.commit()


def get_secret(scope: str, key: str) -> str:
    _assert_secrets_unlocked()
    owner = require_user_id()
    with db_session() as db:
        row = db.scalar(select(EncryptedSecret).where(EncryptedSecret.owner_id == owner, EncryptedSecret.scope == scope, EncryptedSecret.secret_key == key))
        if not row:
            return ""
        try:
            return _fernet().decrypt(row.ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise SecretUnavailableError("No se pudieron descifrar los secretos. Verificá la clave maestra; no se modificó ningún dato.") from exc


def delete_secret(scope: str, key: str) -> None:
    _assert_secrets_unlocked()
    owner = require_user_id()
    with db_session() as db:
        db.execute(delete(EncryptedSecret).where(EncryptedSecret.owner_id == owner, EncryptedSecret.scope == scope, EncryptedSecret.secret_key == key))
        db.commit()


def require_user_id() -> str:
    user_id = current_user_id.get()
    if not user_id:
        raise AuthenticationError("La sesión no está autenticada.")
    return user_id


def load_project_state(project_key: str, default: dict[str, Any]) -> tuple[dict[str, Any], int]:
    owner = require_user_id()
    with db_session() as db:
        row = db.scalar(select(ProjectState).where(ProjectState.owner_id == owner, ProjectState.project_key == project_key))
        if not row:
            return default, 0
        return json.loads(json.dumps(row.data)), row.version


def save_project_state(project_key: str, data: dict[str, Any]) -> int:
    owner = require_user_id()
    expected = expected_project_version.get()
    now = datetime.now(timezone.utc)
    with db_session() as db:
        row = db.scalar(select(ProjectState).where(ProjectState.owner_id == owner, ProjectState.project_key == project_key))
        if row is None:
            if expected not in {None, 0}:
                raise ConcurrentUpdateError("El proyecto cambió. Recargá la página antes de guardar.")
            row = ProjectState(id=str(uuid4()), owner_id=owner, project_key=project_key, version=1, data=data, updated_at=now)
            db.add(row)
            next_version = 1
        else:
            if expected is None or row.version != expected:
                raise ConcurrentUpdateError("Otro usuario o pestaña modificó este proyecto. Recargá antes de guardar.")
            next_version = expected + 1
            changed = db.execute(
                update(ProjectState)
                .where(ProjectState.id == row.id, ProjectState.version == expected)
                .values(version=next_version, data=data, updated_at=now)
            )
            if changed.rowcount != 1:
                db.rollback()
                raise ConcurrentUpdateError("Otro usuario o pestaña modificó este proyecto. Recargá antes de guardar.")
        db.commit()
        saved_project_version.set(next_version)
        metadata = request_metadata.get()
        if metadata is not None:
            metadata["saved_project_version"] = next_version
        expected_project_version.set(next_version)
        return next_version


def get_style_guide_state(project_key: str) -> dict[str, Any] | None:
    owner = require_user_id()
    with db_session() as db:
        row = db.scalar(select(StyleGuideState).where(StyleGuideState.owner_id == owner, StyleGuideState.project_key == project_key))
        if not row:
            return None
        return {"content": row.content, "filename": row.filename, "updated_at": row.updated_at.isoformat(), "version": row.version}


def save_style_guide_state(project_key: str, content: str, filename: str) -> dict[str, Any]:
    owner = require_user_id()
    now = datetime.now(timezone.utc)
    with db_session() as db:
        row = db.scalar(select(StyleGuideState).where(StyleGuideState.owner_id == owner, StyleGuideState.project_key == project_key))
        if row:
            expected = expected_style_guide_version.get()
            if expected is None or row.version != expected:
                raise ConcurrentUpdateError("La guía fue modificada en otra pestaña. Recargá antes de guardar.")
            row.content = content
            row.filename = filename
            row.version += 1
            row.updated_at = now
        else:
            row = StyleGuideState(id=str(uuid4()), owner_id=owner, project_key=project_key, filename=filename, content=content, version=1, updated_at=now)
            db.add(row)
        db.commit()
        return {"content": row.content, "filename": row.filename, "updated_at": row.updated_at.isoformat(), "version": row.version}


def delete_style_guide_state(project_key: str) -> None:
    owner = require_user_id()
    with db_session() as db:
        row = db.scalar(select(StyleGuideState).where(StyleGuideState.owner_id == owner, StyleGuideState.project_key == project_key))
        expected = expected_style_guide_version.get()
        if row and (expected is None or row.version != expected):
            raise ConcurrentUpdateError("La guía fue modificada en otra pestaña. Recargá antes de eliminarla.")
        db.execute(delete(StyleGuideState).where(StyleGuideState.owner_id == owner, StyleGuideState.project_key == project_key))
        db.commit()


def audit(action: str, details: dict[str, Any], project_key: str | None = None, actor_id: str | None = None) -> None:
    if not SERVER_MODE or SessionLocal is None:
        return
    with db_session() as db:
        db.add(AuditEvent(id=str(uuid4()), user_id=actor_id if actor_id is not None else current_user_id.get(), action=action, project_key=project_key, details=details))
        db.commit()
