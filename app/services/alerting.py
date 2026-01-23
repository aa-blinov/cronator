"""Email alerting service."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.config import get_settings
from app.models.execution import Execution
from app.models.script import Script

logger = logging.getLogger(__name__)
settings = get_settings()


class AlertingService:
    """Service for sending email alerts."""

    def __init__(self) -> None:
        # Default values from env, will be overridden by DB settings
        self.enabled = settings.smtp_enabled
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.user = settings.smtp_user
        self.password = settings.smtp_password
        self.from_addr = settings.smtp_from or settings.smtp_user
        self.to_addr = settings.alert_email
        self.use_tls = settings.smtp_use_tls

    async def _get_settings(self) -> dict:
        """Get current settings from DB, fallback to env."""
        from app.services.settings_service import settings_service
        
        smtp_from = await settings_service.get("smtp_from", self.from_addr)
        smtp_user = await settings_service.get("smtp_user", self.user)
        
        return {
            "enabled": await settings_service.get("smtp_enabled", self.enabled),
            "host": await settings_service.get("smtp_host", self.host),
            "port": await settings_service.get("smtp_port", self.port),
            "user": smtp_user,
            "password": await settings_service.get("smtp_password", self.password),
            "from_addr": smtp_from or smtp_user,
            "to_addr": await settings_service.get("alert_email", self.to_addr),
            "use_tls": await settings_service.get("smtp_use_tls", self.use_tls),
        }

    async def send_email(
        self,
        subject: str,
        body_html: str,
        body_text: str | None = None,
    ) -> bool:
        """Send an email alert."""
        # Get current settings from DB
        cfg = await self._get_settings()
        
        if not cfg["enabled"]:
            logger.debug("Email alerts disabled, skipping")
            return False

        if not cfg["to_addr"]:
            logger.warning("No alert email configured")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = cfg["from_addr"]
            msg["To"] = cfg["to_addr"]

            if body_text:
                msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))

            await aiosmtplib.send(
                msg,
                hostname=cfg["host"],
                port=cfg["port"],
                username=cfg["user"],
                password=cfg["password"],
                use_tls=cfg["use_tls"],
            )

            logger.info(f"Alert email sent to {self.to_addr}: {subject}")
            return True

        except Exception as e:
            logger.exception(f"Failed to send alert email: {e}")
            return False

    async def send_failure_alert(self, script: Script, execution: Execution) -> bool:
        """Send an alert for a failed execution."""
        subject = f"[Cronator] ✗ Script Failed: {script.name}"
        
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #dc2626;">Script Execution Failed</h2>
            
            <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                <tr>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;
                        font-weight: bold;">Script</td>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;">
                        {script.name}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;
                        font-weight: bold;">Status</td>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;
                        color: #dc2626;">{execution.status}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;
                        font-weight: bold;">Exit Code</td>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;">
                        {execution.exit_code or 'N/A'}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;
                        font-weight: bold;">Started At</td>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;">
                        {execution.started_at}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;
                        font-weight: bold;">Duration</td>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;">
                        {execution.duration_formatted}</td>
                </tr>
            </table>
            
            {f'''
            <h3>Error Message</h3>
            <pre style="background: #fef2f2; padding: 15px;
border-radius: 4px; overflow-x: auto;">{execution.error_message}</pre>
            ''' if execution.error_message else ''}
            
            {f'''
            <h3>Stderr Output</h3>
            <pre style="background: #fef2f2; padding: 15px;
border-radius: 4px; overflow-x: auto; max-height: 300px;">
{execution.stderr[:2000]}{'...' if len(execution.stderr) > 2000 else ''}
</pre>
            ''' if execution.stderr else ''}
            
            <p style="color: #6b7280; font-size: 12px; margin-top: 30px;">
                This alert was sent by Cronator. 
                <a href="#">View Execution Details</a>
            </p>
        </body>
        </html>
        """

        body_text = f"""
Script Execution Failed

Script: {script.name}
Status: {execution.status}
Exit Code: {execution.exit_code or 'N/A'}
Started At: {execution.started_at}
Duration: {execution.duration_formatted}

Error: {execution.error_message or 'See stderr'}

Stderr:
{execution.stderr[:1000]}{'...' if len(execution.stderr) > 1000 else ''}
        """

        return await self.send_email(subject, body_html, body_text)

    async def send_success_alert(self, script: Script, execution: Execution) -> bool:
        """Send an alert for a successful execution."""
        subject = f"[Cronator] Script Succeeded: {script.name}"
        
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #16a34a;">Script Execution Succeeded</h2>
            
            <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                <tr>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;
                        font-weight: bold;">Script</td>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;">
                        {script.name}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;
                        font-weight: bold;">Status</td>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;
                        color: #16a34a;">{execution.status}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;
                        font-weight: bold;">Started At</td>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;">
                        {execution.started_at}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;
                        font-weight: bold;">Duration</td>
                    <td style="padding: 8px; border: 1px solid #e5e7eb;">
                        {execution.duration_formatted}</td>
                </tr>
            </table>
            
            <p style="color: #6b7280; font-size: 12px; margin-top: 30px;">
                This alert was sent by Cronator.
            </p>
        </body>
        </html>
        """

        return await self.send_email(subject, body_html)

    async def test_connection(self) -> tuple[bool, str]:
        """Test SMTP connection."""
        # Get current settings from DB
        cfg = await self._get_settings()
        
        if not cfg["enabled"]:
            return False, "SMTP is disabled"

        try:
            async with aiosmtplib.SMTP(
                hostname=cfg["host"],
                port=cfg["port"],
                start_tls=cfg["use_tls"],
            ) as smtp:
                await smtp.login(cfg["user"], cfg["password"])
                return True, "Connection successful"
        except Exception as e:
            return False, str(e)


# Global instance
alerting_service = AlertingService()
