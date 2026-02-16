from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class UserInfo:
    sub: str
    name: str
    email: str
    roles: List[str] = field(default_factory=list)
    realm_roles: List[str] = field(default_factory=list)
    preferred_username: Optional[str] = None
    token_exp: Optional[int] = None

    @classmethod
    def from_jwt_claims(cls, claims: dict, resource_id: Optional[str] = None) -> "UserInfo":
        realm_roles = claims.get("realm_access", {}).get("roles", [])

        client_roles = []
        if resource_id:
            resource_access = claims.get("resource_access", {})
            client_roles = resource_access.get(resource_id, {}).get("roles", [])

        return cls(
            sub=claims.get("sub", ""),
            name=claims.get("name", ""),
            email=claims.get("email", ""),
            roles=client_roles,
            realm_roles=realm_roles,
            preferred_username=claims.get("preferred_username"),
            token_exp=claims.get("exp"),
        )
