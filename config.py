import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# If true, the API will require clients to provide their own key via Authorization: Bearer <key>
REQUIRE_BYOK = os.getenv("REQUIRE_BYOK", "false").lower() == "true"

# Default client for local development/tests (not used when BYOK enforced)
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else Groq(api_key="")


def get_groq_client(api_key: str | None):
    """Return a Groq client depending on BYOK setting.
    - If REQUIRE_BYOK is true: a provided api_key is required, otherwise ValueError.
    - If REQUIRE_BYOK is false: use provided api_key if present, else the default client.
    """
    if REQUIRE_BYOK:
        if not api_key:
            raise ValueError("API key required. Provide Authorization: Bearer <key> header.")
        return Groq(api_key=api_key)
    # Not enforced: prefer provided key if any
    if api_key:
        return Groq(api_key=api_key)
    return groq_client
