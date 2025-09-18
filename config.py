import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# If true, the API will require clients to provide their own key via Authorization: Bearer <key>
REQUIRE_BYOK = os.getenv("REQUIRE_BYOK", "false").lower() == "true"

# Default client for local development/tests (not used when BYOK enforced)
# IMPORTANT: Do NOT construct a client with an empty key; raise helpful error instead.
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


def get_groq_client(api_key: str | None):
    """Return a Groq client depending on BYOK setting.
    - If REQUIRE_BYOK is true: a provided api_key is required, otherwise ValueError.
    - If REQUIRE_BYOK is false: use provided api_key if present, else the server key if configured.
    - If neither is available, raise ValueError so the caller can return HTTP 401 with a clear message.
    """
    if api_key:
        return Groq(api_key=api_key)
    if REQUIRE_BYOK:
        raise ValueError("API key required. Provide Authorization: Bearer <key> header.")
    if groq_client is not None:
        return groq_client
    raise ValueError("Server-side API key missing. Set GROQ_API_KEY or enable BYOK.")
