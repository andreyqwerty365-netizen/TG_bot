"""Keep legacy root pytest collection independent of the CRM environment."""
from pathlib import Path


def pytest_ignore_collect(collection_path, config):
    if config.rootpath != Path(__file__).parent:
        return True
    return None
