"""Mailversand: SMTP oder Microsoft Graph, hinter einer gemeinsamen Schnittstelle."""

from magister_api.mail.sender import (
    MailConfig,
    MailError,
    MailMessage,
    MailNotConfiguredError,
    mail_config_from,
    send_mail,
)

__all__ = [
    "MailConfig",
    "MailError",
    "MailMessage",
    "MailNotConfiguredError",
    "mail_config_from",
    "send_mail",
]
