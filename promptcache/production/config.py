"""Central runtime configuration seams for the production deployment."""
import os


def jwt_secret() -> str:
    """Signing secret for dashboard JWTs. Must be overridden via JWT_SECRET in production."""
    return os.getenv("JWT_SECRET", "unsafe-development-secret")
