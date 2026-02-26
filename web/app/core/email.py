"""Email service using Resend API."""

import logging

from web.app.core.config import settings

logger = logging.getLogger(__name__)

# Lazy import — resend may not be installed in test environments
_resend = None


def _get_resend():
    global _resend
    if _resend is None:
        import resend
        resend.api_key = settings.resend_api_key
        _resend = resend
    return _resend


async def send_password_reset(email: str, reset_token: str, base_url: str) -> bool:
    """Send a password reset email.

    Args:
        email: Recipient email.
        reset_token: JWT reset token.
        base_url: Frontend base URL for the reset link.

    Returns:
        True if sent successfully.
    """
    reset_link = f"{base_url}/reset-password?token={reset_token}"

    try:
        resend = _get_resend()
        resend.Emails.send({
            "from": settings.email_from,
            "to": [email],
            "subject": "Voice Studio — Password Reset",
            "html": f"""
            <h2>Password Reset</h2>
            <p>Click the link below to reset your password. This link expires in 1 hour.</p>
            <p><a href="{reset_link}">Reset Password</a></p>
            <p>If you didn't request this, ignore this email.</p>
            """,
        })
        logger.info("Password reset email sent to %s", email)
        return True
    except Exception:
        logger.exception("Failed to send password reset email to %s", email)
        return False


async def send_verification_email(email: str, verify_token: str, base_url: str) -> bool:
    """Send an email verification link.

    Args:
        email: Recipient email.
        verify_token: JWT verification token.
        base_url: Frontend base URL.

    Returns:
        True if sent successfully.
    """
    verify_link = f"{base_url}/verify-email?token={verify_token}"

    try:
        resend = _get_resend()
        resend.Emails.send({
            "from": settings.email_from,
            "to": [email],
            "subject": "Voice Studio — Verify Your Email",
            "html": f"""
            <h2>Welcome to Voice Studio</h2>
            <p>Click the link below to verify your email address.</p>
            <p><a href="{verify_link}">Verify Email</a></p>
            """,
        })
        logger.info("Verification email sent to %s", email)
        return True
    except Exception:
        logger.exception("Failed to send verification email to %s", email)
        return False
