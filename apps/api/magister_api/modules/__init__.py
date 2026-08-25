"""M6 feature-module registry (ADR-0008).

A *module* groups the routers that make up one feature area. ``create_app``
mounts the routers of every enabled module (see ``registry.enabled_modules``)
instead of hard-listing them. Phase 0 is a pure refactor: every module is
enabled, so the mounted route set is unchanged.
"""
