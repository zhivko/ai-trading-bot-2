# Authentication utilities for the trading application

import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import Request, HTTPException, Depends
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from dataclasses import dataclass
from config import AUTH_CREDS_FILE
from logging_config import logger

@dataclass(frozen=True)
class BybitCredentials:
    api_key: str
    api_secret: str
    TRUSTED_CLIENT_CERT_SUBJECTS: List[str]
    GOOGLE_CLIENT_ID: str
    DEEPSEEK_API_KEY: str
    GEMINI_API_KEY: str
    SMTP_SERVER: str
    SMTP_PORT: int
    gmailEmail: str
    gmailPwd: str
    GOOGLE_CLIENT_SECRET: str

    @classmethod
    def from_file(cls, path: Path) -> "BybitCredentials":
        if not path.is_file():
            logger.warning(f"Credentials file not found at {path}. Using placeholder credentials.")
            return cls(
                api_key="YOUR_BYBIT_API_KEY",
                api_secret="YOUR_BYBIT_API_SECRET",
                TRUSTED_CLIENT_CERT_SUBJECTS=[],
                GOOGLE_CLIENT_ID="",
                DEEPSEEK_API_KEY="",
                GEMINI_API_KEY="",
                SMTP_SERVER="",
                SMTP_PORT=0,
                gmailEmail="",
                gmailPwd="",
                GOOGLE_CLIENT_SECRET=""
            )

        creds_text = path.read_text(encoding="utf-8")
        try:
            creds_json = json.loads(creds_text)
            return cls(
                api_key=creds_json["kljuc"],
                api_secret=creds_json["geslo"],
                TRUSTED_CLIENT_CERT_SUBJECTS=creds_json.get("TRUSTED_CLIENT_CERT_SUBJECTS", []),
                DEEPSEEK_API_KEY=creds_json.get("DEEPSEEK_API_KEY"),
                GEMINI_API_KEY=creds_json.get("GEMINI_API_KEY"),
                GOOGLE_CLIENT_ID=creds_json.get("GOOGLE_CLIENT_ID"),
                GOOGLE_CLIENT_SECRET=creds_json.get("GOOGLE_CLIENT_SECRET"),
                SMTP_SERVER=creds_json.get("SMTP_SERVER"),
                SMTP_PORT=creds_json.get("SMTP_PORT", 0),
                gmailEmail=creds_json.get("gmailEmail"),
                gmailPwd=creds_json.get("gmailPwd")
                )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error reading credentials file {path}: {e}. Using placeholder credentials.")
            return cls(
                api_key="YOUR_BYBIT_API_KEY",
                api_secret="YOUR_BYBIT_API_SECRET",
                TRUSTED_CLIENT_CERT_SUBJECTS=[],
                GOOGLE_CLIENT_ID="",
                DEEPSEEK_API_KEY="",
                GEMINI_API_KEY="",
                SMTP_SERVER="",
                SMTP_PORT=0,
                gmailEmail="",
                gmailPwd="",
                GOOGLE_CLIENT_SECRET=""
            )

# Load credentials
creds = BybitCredentials.from_file(AUTH_CREDS_FILE)

async def get_session(request: Request) -> dict:
    """Dependency to retrieve the session."""
    return request.session

def is_authenticated(session: dict = Depends(get_session)):
    """Check if user is authenticated based on session."""
    return session.get("authenticated", False)

def require_authentication(session: dict = Depends(get_session)):
    """Dependency to require authentication for a route."""
    if not is_authenticated(session):
        raise HTTPException(status_code=403, detail="Not authenticated")

def require_valid_certificate(request: Request):
    """
    Dependency function to enforce client certificate validation on a specific route.
    To be used with `Depends()` in a route decorator.
    It checks for headers set by a reverse proxy (e.g., Nginx) performing mTLS.
    """
    client_verify_status = request.headers.get("X-SSL-Client-Verify")

    # Case 1: A valid certificate was presented and verified by the proxy.
    if client_verify_status == "SUCCESS":
        client_subject_dn = request.headers.get("X-SSL-Client-S-DN")
        client_full_cert_pem = request.headers.get("X-SSL-Client-Cert")

        if not client_full_cert_pem:
            logger.warning(f"mTLS SUCCESS but 'X-SSL-Client-Cert' header missing. Subject: {client_subject_dn}")
            raise HTTPException(status_code=403, detail="Client certificate PEM not provided by proxy.")

        try:
            cert = x509.load_pem_x509_certificate(client_full_cert_pem.encode('utf-8'))
            if str(cert.subject) not in creds.TRUSTED_CLIENT_CERT_SUBJECTS:
                logger.warning(f"Unauthorized client certificate subject: {cert.subject}")
                raise HTTPException(status_code=403, detail="Client certificate not authorized.")
            logger.info(f"Client authenticated and authorized via mTLS. Subject: {cert.subject}")
            return True  # Indicate success
        except Exception as e:
            logger.error(f"Error processing client certificate: {e}. Subject: {client_subject_dn}", exc_info=True)
            raise HTTPException(status_code=403, detail="Invalid or unprocessable client certificate.")

    # Case 2: An invalid certificate was presented.
    elif client_verify_status and "FAILED" in client_verify_status:
        client_subject_dn = request.headers.get("X-SSL-Client-S-DN", "N/A")
        logger.warning(f"Client certificate verification FAILED by proxy. Subject: {client_subject_dn}, Status: {client_verify_status}")
        raise HTTPException(status_code=403, detail="Client certificate verification failed.")

    # Case 3: No certificate was presented.
    else:
        logger.warning("Client certificate not present.")
        raise HTTPException(status_code=403, detail="Client certificate not present.")

def require_valid_google_session(request: Request):
    """Dependency to check for a valid Google account session."""
    # Implement session check (e.g., check for a session cookie)
    # If session is invalid, raise HTTPException(status_code=403, detail="Invalid Google session")
    # Replace this with your actual session validation logic
    return True  # Placeholder: Always returns True, needs actual session logic