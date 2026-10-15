"""Server-only owner password configuration; browser origin is explicit."""
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class WebAuthConfig:
    password_hash: str = field(default='', repr=False)
    origin: str = ''
    allow_insecure_localhost: bool = False

    def valid(self,environment):
        try:
            origin=urlsplit(self.origin)
            if (not self.password_hash.startswith('$argon2id$') or not origin.hostname or not origin.netloc
                or origin.path or origin.query or origin.fragment or origin.username or origin.password):
                return False
            if self.allow_insecure_localhost:
                return environment!='production' and origin.scheme=='http' and origin.hostname in ('127.0.0.1','localhost','::1')
            return origin.scheme=='https'
        except ValueError:
            return False

    @classmethod
    def from_env(cls):
        return cls(os.getenv('CRM_WEB_PASSWORD_HASH',''), os.getenv('CRM_WEB_ORIGIN',''),
                   os.getenv('CRM_WEB_INSECURE_LOCALHOST','false').lower() == 'true')
