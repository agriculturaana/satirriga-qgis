from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class UserInfo:
    sub: str
    name: str
    email: str
    roles: List[str] = field(default_factory=list)
    preferred_username: Optional[str] = None
    token_exp: Optional[int] = None

    @classmethod
    def from_jwt_claims(cls, claims: dict) -> "UserInfo":
        realm_access = claims.get("realm_access", {})
        roles = realm_access.get("roles", [])
        return cls(
            sub=claims.get("sub", ""),
            name=claims.get("name", ""),
            email=claims.get("email", ""),
            roles=roles,
            preferred_username=claims.get("preferred_username"),
            token_exp=claims.get("exp"),
        )
