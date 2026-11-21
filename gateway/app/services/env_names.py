"""One reader for this service's own prefixed environment variables (#1017).

ips.pdhc is becoming eps.pdhc (epic #1015). Its own settings used to be
named ``IPS_<NAME>``; the new name is ``EPS_<NAME>``. During the transition
both are accepted:

    EPS_<NAME>  wins when it is set and non-empty;
    IPS_<NAME>  is the fallback;
    neither     -> ``default``, which is whatever the setting defaulted to
                   before #1017. Nothing here invents a value.

An EMPTY string counts as unset, for both names. Otherwise an operator who
adds ``EPS_X=`` as a placeholder would silently mask a working ``IPS_X``.

Only the environment VARIABLE names change. The Flask config keys stay
``IPS_<NAME>`` (tests and call sites read those), and stored data values are
untouched.
"""
from __future__ import annotations

import os

NEW_PREFIX = "EPS_"
OLD_PREFIX = "IPS_"

_TRUE = frozenset({"1", "true", "yes", "on"})


def env_value(name: str, default: str | None = None) -> str | None:
    """``EPS_<name>`` first, then ``IPS_<name>``, else ``default``."""
    for prefix in (NEW_PREFIX, OLD_PREFIX):
        val = os.environ.get(prefix + name)
        if val is not None and val.strip() != "":
            return val
    return default


def env_flag(name: str) -> bool:
    """A boolean setting. Unset (both names empty) is False."""
    val = env_value(name)
    return val is not None and val.strip().lower() in _TRUE


def env_source(name: str) -> str | None:
    """Which variable name supplied ``name`` -- for logs; never the value."""
    for prefix in (NEW_PREFIX, OLD_PREFIX):
        val = os.environ.get(prefix + name)
        if val is not None and val.strip() != "":
            return prefix + name
    return None
