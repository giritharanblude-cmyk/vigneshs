"""Email sender — builds and sends the daily intelligence email."""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

DASHBOARD_URL_ENV = "DASHBOARD_URL"


def _load_dashboard_url() -> str:
    """Load dashboard URL from env or default to placeholder."""
    return os.getenv(DASHBOARD_URL_ENV, "https://YOUR_USERNAME.github.io/softskill-ai-trends/dashboard/")


def build_email_html(date_str: str, report_lines: list[str], dashboard_url: str) -> str:
    """Build the HTML body of the daily report email."""
    components = []
    for line in report_lines:
        clean = line.strip()
        if not clean:
            components.append("<br/>")
        elif clean.isupper() and len(clean) > 3:
            components.append(f"<h2 style='color:#1a365d;'>{clean}</h2>")
        elif clean.startswith(("1.", "2.", "3.", "4.", "5.")):
            components.append(f"<p>{clean}</p>")
        elif clean.startswith("•"):
            components.append(f"<p style='margin-left:20px;'>{clean}</p>")
        elif line.startswith("="):
            continue
        elif line.startswith("-"):
            continue
        else:
            components.append(f"<p>{clean}</p>")

    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 700px; margin: auto; padding: 20px;">
        <div style="background: #1a365d; color: white; padding: 20px; border-radius: 8px;">
            <h1 style="margin: 0;">AI Soft-Skills Intelligence</h1>
            <p style="margin: 5px 0 0; color: #CBD5E0;">Daily Report — {date_str}</p>
        </div>
        <div style="padding: 10px 0;">
            {''.join(components)}
        </div>
        <div style="margin-top: 20px; padding: 15px; background: #F7FAFC; border-radius: 8px; text-align: center;">
            <a href="{dashboard_url}" style="background: #2B6CB0; color: white; padding: 12px 24px;
                text-decoration: none; border-radius: 5px; display: inline-block;">
                View Interactive Dashboard
            </a>
        </div>
        <p style="color: #718096; font-size: 12px; margin-top: 20px;">
            This is an automated intelligence report. Figures marked as "estimated" are modelled;
            "calculated" figures are derived from source data; "observed" figures are reported directly
            by the source. All findings should be verified against primary sources.
        </p>
    </div>
    """


def send_email(
    subject: str,
    html_body: str,
    recipient: str,
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
) -> bool:
    """Send an HTML email via authenticated SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = recipient

    part = MIMEText(html_body, "html")
    msg.attach(part)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.sendmail(username, [recipient], msg.as_string())
        return True
    except Exception as e:
        print(f"[email] Failed to send: {e}")
        return False


def send_daily_email(date_str: str, report_path: Path, recipient: str) -> bool:
    """High-level daily email sender using environment credentials."""
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("EMAIL_USERNAME")
    password = os.getenv("EMAIL_PASSWORD")

    if not (smtp_host and username and password):
        print("[email] SMTP configuration missing — email not sent.")
        print("[email] Set SMTP_HOST, SMTP_PORT, EMAIL_USERNAME, EMAIL_PASSWORD env vars.")
        return False

    report_lines = report_path.read_text(encoding="utf-8").splitlines()
    dashboard_url = _load_dashboard_url()
    subject = f"Daily AI Soft-Skills Intelligence — {date_str}"
    html = build_email_html(date_str, report_lines, dashboard_url)

    return send_email(subject, html, recipient, smtp_host, smtp_port, username, password)
