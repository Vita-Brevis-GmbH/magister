"""Active Directory integration: ldap3 ServerPool + sync + listing.

Public surface:
- :class:`AdClient` — async-friendly wrapper around ldap3 (uses ``run_in_threadpool``)
- :class:`AdUserRecord` — typed view of a search result, ready to upsert into ad_user_cache
- :class:`AdUnavailableError` — raised when all DCs from the pool are exhausted
"""

from magister_api.ad.client import AdClient, AdUserRecord
from magister_api.ad.errors import AdUnavailableError, AdUserParseError

__all__ = [
    "AdClient",
    "AdUnavailableError",
    "AdUserParseError",
    "AdUserRecord",
]
