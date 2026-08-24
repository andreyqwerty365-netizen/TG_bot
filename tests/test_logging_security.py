import logging

from main import SecretRedactionFilter


def test_secret_redaction_filter_hides_configured_and_token_shaped_values():
    token = "123456789:" + "abcdefghijklmnopqrstuvwxyzABCDE"
    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        "POST https://api.telegram.org/bot%s/getUpdates",
        (token,),
        None,
    )

    assert SecretRedactionFilter(token).filter(record)
    message = record.getMessage()

    assert token not in message
    assert "<redacted>" in message
