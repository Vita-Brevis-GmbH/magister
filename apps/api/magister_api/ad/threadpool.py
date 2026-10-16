"""``run_in_threadpool`` ohne Abhängigkeit von einem Web-Framework.

Die Regel aus CLAUDE.md bleibt unverändert: **niemals** synchrone LDAP-Calls im
async Request-Pfad, immer in ``run_in_threadpool`` gewickelt. Nur die Herkunft
der Funktion ändert sich.

Warum: ``fastapi.concurrency.run_in_threadpool`` ist ein Re-Export von
``starlette.concurrency.run_in_threadpool``, und das ist wörtlich
``anyio.to_thread.run_sync(functools.partial(...))`` — nachgelesen, nicht
vermutet. Der Import zog damit FastAPI und Starlette in die AD-Schicht, und
die AD-Schicht wird seit ADR-0014 auch vom **Connector-Agenten** benutzt. Ein
Agent, der im Kundennetz als Dienst läuft, soll kein Web-Framework mitbringen:
weniger Angriffsfläche, kleineres Paket, weniger Sicherheitsmeldungen, die
niemanden betreffen.

Semantisch identisch, deshalb derselbe Name — der Code liest sich weiter so,
wie die Regel es verlangt.
"""

from __future__ import annotations

import functools
from collections.abc import Callable

import anyio.to_thread


async def run_in_threadpool[**P, T](func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    bound = functools.partial(func, *args, **kwargs)
    return await anyio.to_thread.run_sync(bound)


__all__ = ["run_in_threadpool"]
