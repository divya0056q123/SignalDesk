from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage


class SMTPEmailSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        security: str,
        public_base_url: str,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.security = security.lower()
        self.public_base_url = public_base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(
            self.host
            and self.sender
            and self.public_base_url
            and self.security in {"starttls", "ssl"}
            and bool(self.username) == bool(self.password)
        )

    def send(self, recipient: str, subject: str, body: str) -> None:
        if not self.configured:
            raise RuntimeError("Password recovery email is not configured")

        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        context = ssl.create_default_context()
        if self.security == "ssl":
            with smtplib.SMTP_SSL(self.host, self.port, timeout=15, context=context) as server:
                self._send_message(server, message)
            return

        with smtplib.SMTP(self.host, self.port, timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            self._send_message(server, message)

    def _send_message(self, server: smtplib.SMTP, message: EmailMessage) -> None:
        if self.username:
            server.login(self.username, self.password)
        server.send_message(message)
