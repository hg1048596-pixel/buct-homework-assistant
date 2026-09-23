# -*- coding: utf-8 -*-
"""邮件通知（SMTP_SSL + 授权码）。"""
import smtplib
from email.message import EmailMessage

from .base import Notifier, NotifyMessage


class EmailNotifier(Notifier):
    name = "email"

    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled") and self.cfg.get("smtp_user")
                    and self.cfg.get("smtp_auth_code") and self.cfg.get("to"))

    def send(self, msg: NotifyMessage) -> None:
        c = self.cfg
        m = EmailMessage()
        m["Subject"] = f"{c.get('subject_prefix', '')}{msg.title}"
        m["From"] = c["smtp_user"]
        to = c["to"]
        m["To"] = ", ".join(to) if isinstance(to, list) else to
        m.set_content(msg.body or msg.title)
        if msg.html:
            m.add_alternative(msg.html, subtype="html")

        host = c.get("smtp_host", "smtp.qq.com")
        port = int(c.get("smtp_port", 465))
        with smtplib.SMTP_SSL(host, port, timeout=20) as s:
            s.login(c["smtp_user"], c["smtp_auth_code"])
            s.send_message(m)
