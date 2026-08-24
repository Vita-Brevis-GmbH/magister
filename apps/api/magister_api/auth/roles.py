"""Role identity constants (leaf module, no auth deps).

Roles are the identity fact stored in ``role_assignments``; *capabilities*
(:mod:`magister_api.auth.capabilities`) are what endpoints require. These
constants live in their own dependency-free module so both ``rbac`` and
``capabilities`` can import them without an import cycle.
"""

from __future__ import annotations

# RBAC tiers.
#   admin         — cross-school super-role (school_id=NULL); holds every
#                   capability implicitly.
#   schulleitung  — per-school; class & teacher management.
#   smi           — per-school Schulträger-IT; cross-school user listing and
#                   password reset for students *and* teachers within their
#                   assigned schools. No system-config powers.
#   kl            — Klassenlehrer; derived from class_teacher_roles (not stored
#                   in role_assignments). Its powers are per-class and live in
#                   :mod:`magister_api.auth.class_perm`, so it maps to no
#                   coarse capability here.
ROLE_ADMIN = "admin"
ROLE_SCHULLEITUNG = "schulleitung"
ROLE_SMI = "smi"
ROLE_KL = "kl"

# Roles that live in ``role_assignments`` (kl is in ``class_teacher_roles``).
ROLE_ASSIGNMENT_ROLES: frozenset[str] = frozenset({ROLE_ADMIN, ROLE_SCHULLEITUNG, ROLE_SMI})
