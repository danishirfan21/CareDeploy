"""Simulated patient verification and server-issued, expiring authorization.

This is a simulated mechanism. It is NOT real-world patient identity proofing.
A client-supplied "verified" flag is never trusted: access requires a bearer token issued by
`verify_patient`, bound to one clinic and one patient, stored only as a SHA-256 hash.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models import Patient, PatientAuthorization
from app.scheduling.errors import (
    AuthenticationRequired,
    AuthorizationExpired,
    Forbidden,
    NotFound,
    VerificationFailed,
    VerificationLocked,
)
from app.schemas.scheduling import VerifyRequest, VerifyResponse


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class AuthContext:
    clinic_id: uuid.UUID
    patient_id: uuid.UUID
    authorization_id: uuid.UUID


async def verify_patient(
    sm: async_sessionmaker[AsyncSession],
    clinic_id: uuid.UUID,
    patient_id: uuid.UUID,
    req: VerifyRequest,
    now: datetime,
) -> VerifyResponse:
    settings = get_settings()
    async with sm() as session:
        patient = await session.scalar(
            select(Patient).where(Patient.clinic_id == clinic_id, Patient.id == patient_id)
        )
        if patient is None:
            raise NotFound("Patient not found.")
        if patient.locked_until is not None and patient.locked_until > now:
            raise VerificationLocked("Too many failed attempts. Try again later.")

        dob_ok = hmac.compare_digest(
            patient.date_of_birth.isoformat(), req.date_of_birth.isoformat()
        )
        phone_ok = hmac.compare_digest(
            "".join(c for c in patient.phone if c.isdigit())[-4:], req.phone_last4
        )
        if not (dob_ok and phone_ok):
            patient.failed_verification_attempts += 1
            if patient.failed_verification_attempts >= settings.verification_max_attempts:
                patient.locked_until = now + timedelta(
                    minutes=settings.verification_lockout_minutes
                )
                patient.failed_verification_attempts = 0
            await session.commit()  # persist the failure before reporting it
            raise VerificationFailed("The details provided did not match our records.")

        token = new_secret()
        expires = now + timedelta(minutes=settings.authorization_ttl_minutes)
        session.add(
            PatientAuthorization(
                clinic_id=clinic_id,
                patient_id=patient_id,
                token_hash=hash_token(token),
                expires_at=expires,
            )
        )
        patient.failed_verification_attempts = 0
        patient.locked_until = None
        patient.last_verified_at = now
        await session.commit()
        return VerifyResponse(
            patient_id=patient_id,
            clinic_id=clinic_id,
            authorization_token=token,
            expires_at=expires,
        )


async def authorize(
    session: AsyncSession, clinic_id: uuid.UUID, bearer: str | None, now: datetime
) -> AuthContext:
    if not bearer:
        raise AuthenticationRequired("A patient authorization token is required.")
    row = await session.scalar(
        select(PatientAuthorization).where(PatientAuthorization.token_hash == hash_token(bearer))
    )
    if row is None:
        raise AuthenticationRequired("The authorization token is not valid.")
    if row.clinic_id != clinic_id:
        raise Forbidden("This authorization does not apply to this clinic.")
    if row.revoked_at is not None or row.expires_at <= now:
        raise AuthorizationExpired("The authorization has expired. Verify the patient again.")
    return AuthContext(clinic_id, row.patient_id, row.id)


def require_patient(ctx: AuthContext, patient_id: uuid.UUID) -> None:
    if ctx.patient_id != patient_id:
        raise Forbidden("This authorization does not apply to this patient.")
