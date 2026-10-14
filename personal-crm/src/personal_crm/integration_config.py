from dataclasses import dataclass, field
import os


def enabled(name):
    return os.getenv(name, "").lower() in ("true", "1")


def ids(name):
    try:
        return frozenset(int(x.strip()) for x in os.getenv(name, "").split(",") if x.strip())
    except ValueError:
        return frozenset()


def number(name, default, convert=int):
    try:
        return convert(os.getenv(name, str(default)))
    except ValueError:
        return 0  # Invalid limits make the provider gate fail closed.


@dataclass(frozen=True)
class AIConfig:
    enabled: bool = False
    key: str = field(default="", repr=False)
    model: str = ""
    allowed_models: frozenset[str] = frozenset()
    consent_categories: frozenset[str] = frozenset()
    monthly_budget_usd: str = "0"
    prices_json: str = "{}"
    max_output_tokens: int = 512
    max_input_chars: int = 8000
    timeout_seconds: float = 8

    @classmethod
    def from_env(cls):
        flag = enabled("CRM_OPENAI_ENABLED")
        return cls(flag, os.getenv("OPENAI_API_KEY", "") if flag else "", os.getenv("CRM_OPENAI_MODEL", ""),
            frozenset(x.strip() for x in os.getenv("CRM_OPENAI_ALLOWED_MODELS", "").split(",") if x.strip()),
            frozenset(x.strip() for x in os.getenv("CRM_AI_CONSENT_CATEGORIES", "").split(",") if x.strip()),
            os.getenv("CRM_OPENAI_MONTHLY_BUDGET_USD", "0"), os.getenv("CRM_OPENAI_PRICES_JSON", "{}"),
            number("CRM_OPENAI_MAX_OUTPUT_TOKENS", 512), number("CRM_OPENAI_MAX_INPUT_CHARS", 8000),
            number("CRM_OPENAI_TIMEOUT_SECONDS", 8, float))


@dataclass(frozen=True)
class TelegramConfig:
    webhook_enabled: bool = False
    send_enabled: bool = False
    webhook_secret: str = field(default="", repr=False)
    test_token: str = field(default="", repr=False)
    bot_id: str = ""
    allowed_user_ids: frozenset[int] = frozenset()
    allowed_chat_ids: frozenset[int] = frozenset()
    outbound_chat_id: int | None = None
    allow_groups: bool = False

    @classmethod
    def from_env(cls):
        chat = os.getenv("CRM_TELEGRAM_OUTBOUND_CHAT_ID", "")
        return cls(enabled("CRM_TELEGRAM_WEBHOOK_ENABLED"), enabled("CRM_TELEGRAM_SEND_ENABLED"),
            os.getenv("CRM_TELEGRAM_WEBHOOK_SECRET", ""),
            os.getenv("CRM_TELEGRAM_TEST_TOKEN", "") if enabled("CRM_TELEGRAM_SEND_ENABLED") else "",
            os.getenv("CRM_TELEGRAM_BOT_ID", ""), ids("CRM_TELEGRAM_ALLOWED_USER_IDS"), ids("CRM_TELEGRAM_ALLOWED_CHAT_IDS"),
            int(chat) if chat.lstrip("-").isdigit() else None, enabled("CRM_TELEGRAM_ALLOW_GROUPS"))
