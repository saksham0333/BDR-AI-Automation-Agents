"""Send lead CSVs to the lead SDR via SMTP (Gmail / Google Workspace)."""

import smtplib
from email.message import EmailMessage
from pathlib import Path

import config


def _send_email_with_attachment(subject: str, body: str, csv_path: Path) -> None:
    config.require_email_config()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM
    msg["To"] = config.SDR_EMAIL
    msg.set_content(body)

    msg.add_attachment(
        csv_path.read_bytes(),
        maintype="text",
        subtype="csv",
        filename=csv_path.name,
    )

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        smtp.send_message(msg)

    print(f"Emailed {csv_path.name} to {config.SDR_EMAIL}")


def send_lead_csv(csv_path: Path, lead_count: int, run_label: str) -> None:
    subject = f"NamaSys qualified leads — {run_label} ({lead_count} leads)"
    body = (
        f"Hi,\n\n"
        f"Attached: {lead_count} leads from today's {run_label} run "
        f"(ICP-scored, deduplicated by domain).\n\n"
        f'Leads scoring under 50 are flagged "LOW PRIORITY: hold for human '
        f'review before routing to outreach" in the Score Breakdown column — '
        f"please review those before routing to outreach.\n\n"
        f"— NamaSys Lead Generation Agent (automated)\n"
    )
    _send_email_with_attachment(subject, body, csv_path)


def send_no_email_leads_for_review(csv_path: Path, lead_count: int) -> None:
    """Sends leads that came back without a contact email to the SDR for
    review — these can't go into HubSpot as Contacts until an email is
    either found or the SDR approves proceeding without one. Once you get
    the reviewed/edited file back, run: python hubspot_sync.py <file>
    """
    subject = f"NamaSys leads needing review — {lead_count} missing an email"
    body = (
        f"Hi,\n\n"
        f"Attached: {lead_count} leads Apollo couldn't find a verified email "
        f"for. Everything else (company, decision-maker name/title, LinkedIn, "
        f"score, fit reasoning) is filled in — please review, and either:\n\n"
        f"  - fill in an email you find manually, or\n"
        f"  - leave it blank if you don't want this lead added to HubSpot, or\n"
        f"  - approve as-is if you want it added to HubSpot without an email "
        f"(update the row however you'd like)\n\n"
        f"Once you're done, send the file back and it'll be synced to "
        f"HubSpot — any row with an email filled in will sync; rows still "
        f"missing one will be skipped.\n\n"
        f"— NamaSys Lead Generation Agent (automated)\n"
    )
    _send_email_with_attachment(subject, body, csv_path)
