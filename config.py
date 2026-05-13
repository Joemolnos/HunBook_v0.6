import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# If true, the API will require clients to provide their own key via Authorization: Bearer <key>
REQUIRE_BYOK = os.getenv("REQUIRE_BYOK", "false").lower() == "true"

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


def _is_openai_model(model: str) -> bool:
    """Return True for models that must be routed to the OpenAI API."""
    m = (model or "").lower()
    return m.startswith(("gpt-", "o1-", "o3-", "o4-", "text-davinci", "chatgpt-"))


def get_groq_client(api_key: str | None):
    """Return a Groq client depending on BYOK setting."""
    if api_key:
        return Groq(api_key=api_key)
    if REQUIRE_BYOK:
        raise ValueError("API key required. Provide Authorization: Bearer <key> header.")
    if groq_client is not None:
        return groq_client
    raise ValueError("Server-side API key missing. Set GROQ_API_KEY or enable BYOK.")


def get_openai_client(api_key: str | None):
    """Return an OpenAI client."""
    from openai import OpenAI
    key = api_key or OPENAI_API_KEY
    if not key:
        raise ValueError(
            "OpenAI API key required. Provide Authorization: Bearer <key> or set OPENAI_API_KEY."
        )
    return OpenAI(api_key=key)


def get_llm_client(model: str, api_key: str | None):
    """Route to the correct provider client based on the model name.

    - gpt-*, o1-*, o3-*, o4-*  → OpenAI
    - everything else           → Groq
    """
    if _is_openai_model(model):
        return get_openai_client(api_key)
    return get_groq_client(api_key)
