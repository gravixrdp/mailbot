"""
╔══════════════════════════════════════════════════════════╗
║     VISHAL'S SMART JOB APPLICATION TELEGRAM BOT         ║
║     Auto-sends personalized emails to companies          ║
║     Duplicate detection | HTML bold formatting           ║
╚══════════════════════════════════════════════════════════╝

SETUP:
  pip install python-telegram-bot==20.7 secure-smtplib

HOW TO USE:
  1. Put your resume PDF as  'resume.pdf'  in same folder
  2. Run:  python job_mailer_bot.py
  3. Open Telegram → your bot
  4. /setpass YOUR_GMAIL_APP_PASSWORD
  5. Send any HR email like:  hr@google.com
  6. Done ✅ Mail sent!

NOTE: Use Gmail APP PASSWORD (not your real password)
  → Google Account → Security → 2-Step Verification → App Passwords
"""

import os
import json
import re
import smtplib
import logging
import asyncio
import ssl
import imaplib
import email as email_pkg
from email.header import decode_header
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ─────────────────────────────────────────────
#  CONFIG  –  fill these before running
# ─────────────────────────────────────────────
BOT_TOKEN   = "8413258612:AAF1VHcO3Wrk7BjjXw0sAClJY4o8Ci0shZA"          # paste your bot token
GMAIL_USER  = "vishalgurjar0444@gmail.com"
GMAIL_PASS  = os.getenv("GMAIL_APP_PASS", "")  # set via /setpass or env var
RESUME_PATH = "vishal_devops_resume.pdf"                   # path to your resume
SENT_LOG    = "sent_log.json"               # auto-created, tracks sent mails
SHEET_CONFIG = "sheet_config.json"          # stores Google Sheet config
BOUNCE_STATE = "bounce_state.json"          # stores last processed IMAP UID for bounce checks
# ─── GCP Sheet Sync (direct via Service Account) ───
SHEET_ID       = os.getenv("SHEET_ID", "1a16BeOSUqfDNHQwzfI55QfUDTCcJZqjIseqnAy5DKGY")
CREDENTIALS_PATH = os.getenv("GCP_CREDENTIALS", "gen-lang-client-0428625036-fcdde7565288.json")
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
#  EMAIL TEMPLATE  (HTML with bold tags preserved)
# ═══════════════════════════════════════════════════════

EMAIL_SUBJECT = (
    "Application for DevOps Engineer Role | Vishal Gurjar | "
    "GCP | AWS | Kubernetes | Terraform | CI/CD"
)

def build_email_body(company_name: str) -> str:
    """Returns full HTML email body with company name injected."""
    return f"""
<html><body style="font-family: Arial, sans-serif; font-size: 14px; color: #1a1a1a; line-height: 1.6;">

<p>Dear Hiring Team,</p>

<p>
I am <strong>Vishal Gurjar</strong>, a <strong>DevOps &amp; Cloud Engineer</strong>
(B.E. Computer Engineering, graduating June 2026) from Ahmedabad, applying for a
<strong>DevOps Engineer role</strong> at <strong>{company_name}</strong>.
</p>

<p>I have <strong>6 months of internship experience</strong> across <strong>GCP</strong> and <strong>AWS</strong>:</p>

<ul>
  <li>Built end-to-end <strong>GCP CI/CD pipeline</strong> using <strong>Cloud Build</strong>,
      <strong>Artifact Registry</strong>, and <strong>Cloud Run</strong> with Cloud SQL,
      eliminating <strong>100%</strong> of manual deployments.</li>

  <li>Architected the <strong>GKE platform</strong> with <strong>Workload Identity Federation</strong>
      and <strong>ArgoCD GitOps</strong>, enabling <strong>sub-5-minute rollbacks</strong>.</li>

  <li>Developed <strong>Apigee X proxies</strong> using <strong>Vertex AI Vector Search</strong>
      for LLM semantic caching and <strong>Cloud DLP</strong> for PII masking.</li>

  <li>Managed <strong>8+ AWS services</strong> (EC2, VPC, S3, ECS, IAM, CloudWatch)
      maintaining <strong>99.9% uptime</strong>.</li>

  <li>Automated operations via <strong>Shell scripting</strong>, reducing manual effort by
      <strong>80%</strong>.</li>
</ul>

<p>
<strong>Core Skills:</strong> Linux | Docker | Kubernetes | Terraform | Jenkins |
GitHub Actions | SonarQube | Trivy | Prometheus | Grafana
</p>

<p>
<strong>Certification:</strong> Oracle Cloud Infrastructure 2025 Certified DevOps Professional
</p>

<p>
Resume is attached for your review.&nbsp;
<strong>Portfolio:</strong> <a href="https://gurjar-vishal.me">gurjar-vishal.me</a> |
<strong>GitHub:</strong> <a href="https://github.com/gurjar-vishal">github.com/gurjar-vishal</a>
</p>

<p>Thank you for your time. I would be happy to connect at your convenience.</p>

<p>
Regards,<br/>
<strong>Vishal Gurjar</strong><br/>
+91 9909083139 | vishalgurjar0444@gmail.com<br/>
<a href="https://linkedin.com/in/vg-ahir-444-devops">linkedin.com/in/vg-ahir-444-devops</a>
</p>

</body></html>
"""

# ═══════════════════════════════════════════════════════
#  SENT-LOG  –  duplicate detection
# ═══════════════════════════════════════════════════════

def load_sent_log() -> dict:
    if os.path.exists(SENT_LOG):
        with open(SENT_LOG, "r") as f:
            return json.load(f)
    return {}          # { "google.com": {"email": "hr@google.com", "time": "..."} }

def save_sent_log(data: dict):
    with open(SENT_LOG, "w") as f:
        json.dump(data, f, indent=2)

def already_sent(domain: str) -> dict | None:
    """Returns the log entry if mail was already sent to this company domain."""
    log = load_sent_log()
    return log.get(domain.lower())

def mark_sent(domain: str, email: str):
    log = load_sent_log()
    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log[domain.lower()] = {
        "email": email,
        "sent_at": sent_at
    }
    save_sent_log(log)
    return sent_at

# ═══════════════════════════════════════════════════════
#  GOOGLE SHEET SYNC (direct via GCP Service Account)
# ═══════════════════════════════════════════════════════

def _get_sheet():
    """Authorize and return the gspread sheet object."""
    import gspread
    from google.oauth2.service_account import Credentials
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scope)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)
    return sh.sheet1


def _read_all_rows(sheet):
    """Read all rows and return (values, domain_map, header_start)."""
    values = sheet.get_values()
    if not values:
        return values, {}, 1
    header_val = str(values[0][0] or "").strip().lower()
    start = 2 if header_val == "domain" else 1
    domain_map = {}
    for i, row in enumerate(values[start - 1:], start=start):
        d = str(row[0] or "").strip().lower()
        if d:
            domain_map[d] = i
    return values, domain_map, start


def sync_sheet_upsert(domain: str, email: str, sent_at: str) -> tuple[bool, str]:
    """Upserts single domain row into Google Sheet (batch write)."""
    try:
        sheet = _get_sheet()
        values, dmap, _ = _read_all_rows(sheet)
        d = domain.lower()
        company = domain_to_company(domain)
        new_row = [d, company, email, sent_at, "yes"]

        if d in dmap:
            r = dmap[d]
            sheet.update(values=[[email, sent_at, "yes"]], range_name=f"C{r}:E{r}")
        else:
            sheet.append_row(new_row)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def sync_sheet_set_status(domain: str, status: str) -> tuple[bool, str]:
    """Update status (col E) for a given domain row."""
    try:
        sheet = _get_sheet()
        _, dmap, _ = _read_all_rows(sheet)
        d = domain.lower()
        if d not in dmap:
            return False, "domain not found"
        r = dmap[d]
        sheet.update(values=[[status]], range_name=f"E{r}:E{r}")
        return True, "ok"
    except Exception as e:
        return False, str(e)


def sync_sheet_all() -> tuple[bool, str, int]:
    """Sync entire sent_log.json to sheet using batch writes."""
    try:
        sheet = _get_sheet()
        values, dmap, _ = _read_all_rows(sheet)
        log = load_sent_log()
        count = 0
        updates = []
        new_rows = []

        for domain, info in log.items():
            d = domain.lower()
            company = domain_to_company(domain)
            email = info.get("email", "")
            sent_at = info.get("sent_at", "")
            if d in dmap:
                r = dmap[d]
                updates.append((r, [email, sent_at, "yes"]))
            else:
                new_rows.append([d, company, email, sent_at, "yes"])
            count += 1

        # Batch update all existing rows in ONE API call
        if updates:
            value_ranges = []
            for r, data in updates:
                value_ranges.append({
                    "range": f"C{r}:E{r}",
                    "values": [data],
                })
            sheet.batch_update(value_ranges)
        if new_rows:
            sheet.append_rows(new_rows)
        return True, "ok", count
    except Exception as e:
        return False, str(e), 0


def sheet_webhook_status() -> tuple[bool, str]:
    """Return sheet info for debugging."""
    try:
        sheet = _get_sheet()
        values, _, _ = _read_all_rows(sheet)
        total = len(values) - 1 if values else 0
        return True, f"sheet={sheet.title}, sheetId={SHEET_ID}, total_rows={total}"
    except Exception as e:
        return False, str(e)


def get_sheet_webhook_url() -> str:
    """Return non-empty if sheet is configured (backward compat shim)."""
    return SHEET_ID if os.path.exists(CREDENTIALS_PATH) else ""


def set_sheet_webhook_url(url: str):
    """No-op kept for backward compatibility."""
    pass


def _sheet_secret() -> str:
    return ""


def set_sheet_secret(secret: str):
    pass


def _should_auto_sync_sheet() -> bool:
    val = os.getenv("AUTO_SYNC_SHEET", "").strip().lower()
    return val in {"1", "true", "yes", "y", "on"}

def _load_bounce_state() -> dict:
    if os.path.exists(BOUNCE_STATE):
        try:
            with open(BOUNCE_STATE, "r") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

def _save_bounce_state(state: dict):
    with open(BOUNCE_STATE, "w") as f:
        json.dump(state, f, indent=2)

def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    try:
        parts = decode_header(value)
        out = []
        for part, enc in parts:
            if isinstance(part, bytes):
                out.append(part.decode(enc or "utf-8", errors="replace"))
            else:
                out.append(str(part))
        return "".join(out).strip()
    except Exception:
        return str(value).strip()

def _extract_bounced_recipients(msg: email_pkg.message.Message) -> set[str]:
    """
    Extract failed recipient emails from bounce messages.
    Strict mode: prefer DSN fields and common Gmail failure lines only.
    Avoid broad "any email in body" extraction to prevent false negatives.
    """
    found: set[str] = set()

    def add_dsn_from_text(text: str):
        if not text:
            return
        # DSN lines: Final-Recipient: rfc822; hr@example.com
        for m in re.finditer(r"rfc822;\s*([^\s<>]+@[^\s<>]+)", text, flags=re.IGNORECASE):
            found.add(m.group(1).lower())
        # Some DSNs include direct fields too.
        for m in re.finditer(r"(?:Final-Recipient|Original-Recipient)\s*:\s*([^\s<>]+@[^\s<>]+)", text, flags=re.IGNORECASE):
            found.add(m.group(1).lower())

    def add_gmail_failure_lines(text: str):
        if not text:
            return
        # Gmail human-readable bounce line:
        # "Your message wasn't delivered to hr@example.com ..."
        low = text.lower()
        for m in re.finditer(r"wasn['’]t delivered to\s+([^\s<>]+@[^\s<>]+)", low, flags=re.IGNORECASE):
            found.add(m.group(1).lower())

    subject = _decode_header_value(msg.get("Subject"))
    add_gmail_failure_lines(subject)

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "message/delivery-status"):
                try:
                    payload = part.get_payload(decode=True) or b""
                    charset = part.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")
                    if ctype == "message/delivery-status":
                        add_dsn_from_text(text)
                    else:
                        add_gmail_failure_lines(text)
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            add_gmail_failure_lines(text)
        except Exception:
            pass

    # Keep only things that look like emails
    return {e for e in found if is_valid_email(e)}

def _is_hard_failure_subject(subject: str) -> bool:
    return "address not found" in (subject or "").strip().lower()

def _message_has_address_not_found(msg: email_pkg.message.Message) -> bool:
    subject = _decode_header_value(msg.get("Subject"))
    if _is_hard_failure_subject(subject):
        return True
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace").lower()
                if "address not found" in text:
                    return True
            except Exception:
                continue
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace").lower()
            if "address not found" in text:
                return True
        except Exception:
            pass
    return False

def check_gmail_bounces_and_update_sheet(force_rescan: bool = False) -> tuple[int, int]:
    """
    Checks Gmail inbox for new bounce messages and updates Google Sheet status to 'no' for affected domains.
    Returns: (bounces_found, rows_updated)
    """
    if not GMAIL_PASS or not get_sheet_webhook_url():
        return 0, 0

    state = _load_bounce_state()
    last_uid = int(state.get("last_uid") or 0)

    context = ssl.create_default_context()
    bounces_found = 0
    updated = 0

    # Reverse map for exact-match of recipients we actually sent to
    sent_log = load_sent_log()
    email_to_domain = {v.get("email", "").lower(): k for k, v in sent_log.items() if isinstance(v, dict) and v.get("email")}

    m = imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=context)
    try:
        m.login(GMAIL_USER, GMAIL_PASS)
        m.select("INBOX")

        # Search for bounce-like senders; command can force-rescan recent UIDs.
        uids: set[int] = set()
        for from_addr in ('"mailer-daemon@googlemail.com"', '"MAILER-DAEMON"', '"postmaster"', '"Mail Delivery Subsystem"'):
            typ, data = m.uid("search", None, f'(FROM {from_addr})')
            if typ != "OK":
                continue
            for x in (data[0] or b"").split():
                try:
                    uid_int = int(x)
                except Exception:
                    continue
                if force_rescan or uid_int > last_uid:
                    uids.add(uid_int)

        if not uids:
            return 0, 0

        # Force mode scans only recent messages to stay fast.
        uid_list = sorted(uids)
        if force_rescan and len(uid_list) > 200:
            uid_list = uid_list[-200:]

        for uid in uid_list:
            typ, msg_data = m.uid("fetch", str(uid), "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue

            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
            if not raw:
                continue

            msg = email_pkg.message_from_bytes(raw)
            subject = _decode_header_value(msg.get("Subject"))
            if not _message_has_address_not_found(msg):
                last_uid = max(last_uid, uid)
                continue
            recipients = _extract_bounced_recipients(msg)
            if not recipients:
                last_uid = max(last_uid, uid)
                continue

            # Strict: only update rows for recipients that exactly match sent_log emails.
            affected_domains: set[str] = set()
            for rcp in recipients:
                domain = email_to_domain.get(rcp, "").lower()
                if domain:
                    affected_domains.add(domain)

            if not affected_domains:
                last_uid = max(last_uid, uid)
                continue

            for domain in affected_domains:
                bounces_found += 1
                ok, _ = sync_sheet_set_status(domain, "no")
                if ok:
                    updated += 1

            # Mark message seen so we don't keep reprocessing if UID state is lost
            try:
                m.uid("store", str(uid), "+FLAGS", "(\\Seen)")
            except Exception:
                pass

            last_uid = max(last_uid, uid)

        state["last_uid"] = last_uid
        _save_bounce_state(state)
        return bounces_found, updated
    finally:
        try:
            m.logout()
        except Exception:
            pass

# ═══════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════

EMAIL_REGEX = re.compile(r"^[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}$")

def is_valid_email(text: str) -> bool:
    return bool(EMAIL_REGEX.match(text.strip()))

def extract_emails(text: str) -> list[str]:
    """
    Extracts potential emails from free-form text (space/newline/comma separated).
    Keeps order, de-dupes (case-insensitive).
    """
    if not text:
        return []
    # Common separators: whitespace, commas, semicolons
    candidates = re.split(r"[\s,;]+", text.strip())
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if not c:
            continue
        c = c.strip().lower()
        if not c:
            continue
        if c in seen:
            continue
        if is_valid_email(c):
            out.append(c)
            seen.add(c)
    return out

def extract_domain(email: str) -> str:
    return email.strip().split("@")[1].lower()

def domain_to_company(domain: str) -> str:
    """
    hr@google.com        → Google
    careers@microsoft.com → Microsoft
    jobs@startup.io      → Startup
    """
    # Remove common subdomains like mail., careers., jobs., hr.
    parts = domain.split(".")
    # Take second-last part as company (e.g. google from google.com)
    # Handle things like careers.google.com → google
    skip_prefixes = {"mail", "careers", "jobs", "hr", "recruit", "hiring",
                     "apply", "talent", "info", "work", "team"}
    meaningful = [p for p in parts[:-1] if p not in skip_prefixes]
    company_raw = meaningful[-1] if meaningful else parts[0]
    return company_raw.capitalize()

# ═══════════════════════════════════════════════════════
#  EMAIL SENDER
# ═══════════════════════════════════════════════════════

def send_application_email(to_email: str, company_name: str, gmail_pass: str) -> str:
    """Sends HTML email with resume attached. Returns 'ok' or error message."""
    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = f"Vishal Gurjar <{GMAIL_USER}>"
        msg["To"]      = to_email
        msg["Subject"] = EMAIL_SUBJECT

        html_body = build_email_body(company_name)
        msg.attach(MIMEText(html_body, "html"))

        # Attach resume if file exists
        resume_attached = False
        if os.path.exists(RESUME_PATH):
            with open(RESUME_PATH, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="Vishal_Gurjar_Resume.pdf"'
            )
            msg.attach(part)
            resume_attached = True

        # Send via Gmail SMTP
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, gmail_pass)
            server.sendmail(GMAIL_USER, to_email, msg.as_string())

        status = "✅ Mail sent successfully!"
        if not resume_attached:
            status += "\n⚠️ resume.pdf not found – mail sent WITHOUT resume."
        return status

    except smtplib.SMTPAuthenticationError:
        return "❌ Gmail auth failed! Check your App Password with /setpass"
    except smtplib.SMTPException as e:
        return f"❌ SMTP error: {e}"
    except Exception as e:
        return f"❌ Unexpected error: {e}"

# ═══════════════════════════════════════════════════════
#  TELEGRAM HANDLERS
# ═══════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Vishal's Smart Job Mailer Bot*\n\n"
        "📌 *Commands:*\n"
        "• `/setpass <app_password>` – Set Gmail App Password\n"
        "• `/setsheet [SHEET_ID]` – Configure Google Sheet\n"
        "• `/sheetstatus` – Check sheet status\n"
        "• `/syncsheet` – Push full sent log to sheet\n"
        "• `/bulk <emails...>` – Send in bulk (10s gap)\n"
        "• `/cancelbulk` – Stop bulk sending\n"
        "• `/checkbounces` – Check Gmail bounces → mark NO\n"
        "• `/log` – View all sent mails\n"
        "• `/clearlog` – Clear the sent history\n\n"
        "📨 *To send mail:*\n"
        "Just type any HR email like:\n`hr@google.com` or `careers@amazon.com`\n\n"
        "🧠 *Smart features:*\n"
        "✔ Auto-detects company name from email domain\n"
        "✔ Replaces company name in mail body\n"
        "✔ Blocks duplicate mails to same company\n"
        "✔ Attaches your resume automatically\n"
        "✔ Sends bold-formatted HTML email\n"
        "✔ Syncs directly to Google Sheet via GCP"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_setpass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global GMAIL_PASS
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "❌ Usage: `/setpass YOUR_APP_PASSWORD`\n\n"
            "Get it from:\nGoogle Account → Security → 2-Step Verification → App Passwords",
            parse_mode="Markdown"
        )
        return
    GMAIL_PASS = " ".join(args).strip()
    await update.message.reply_text(
        "✅ Gmail App Password saved!\nNow send any HR email to start mailing.",
        parse_mode="Markdown"
    )

async def cmd_setsheet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Configure sheet or set a custom Sheet ID.
    Usage: /setsheet (shows current) or /setsheet <SHEET_ID>
    Also accepts webhook URL for backward compatibility."""
    args = ctx.args
    if not args:
        ok, msg = await asyncio.to_thread(sheet_webhook_status)
        if ok:
            await update.message.reply_text(
                f"ℹ️ Sheet config:\n`{msg}`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"❌ Sheet config: `{msg}`\n\n"
                "Use: `/setsheet <SHEET_ID>` to set a custom Google Sheet ID.",
                parse_mode="Markdown",
            )
        return
    value = " ".join(args).strip()
    # If it looks like a webhook URL, store it for backward compat
    if value.startswith("https://"):
        set_sheet_webhook_url(value)
        await update.message.reply_text(
            "✅ Sheet webhook saved (backward compat mode).",
            parse_mode="Markdown",
        )
        return
    # Otherwise treat as a Sheet ID
    set_sheet_webhook_url(value)
    await update.message.reply_text(
        f"✅ Sheet ID saved. Now run `/syncsheet`.",
        parse_mode="Markdown",
    )

async def cmd_setsecret(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Secret is no longer needed — the bot uses GCP Service Account credentials directly.",
        parse_mode="Markdown",
    )

async def cmd_syncsheet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not get_sheet_webhook_url():
        await update.message.reply_text(
            "⚠️ Sheet not configured.\n"
            "Place GCP credentials as `gen-lang-client-0428625036-fcdde7565288.json` in this folder.\n"
            "Or set SHEET_ID env var.",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text("🔄 Syncing sent log to Google Sheet...", parse_mode="Markdown")

    def _sync():
        return sync_sheet_all()

    ok, msg, count = await asyncio.to_thread(_sync)
    if ok:
        await update.message.reply_text(f"✅ Synced `{count}` companies to sheet.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Sheet sync failed: `{msg}`", parse_mode="Markdown")

async def cmd_sheetstatus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ok, msg = await asyncio.to_thread(sheet_webhook_status)
    if ok:
        await update.message.reply_text(f"ℹ️ Sheet status: `{msg}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Sheet status failed: `{msg}`", parse_mode="Markdown")

async def cmd_bulk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Bulk sender – takes many emails and sends them one-by-one with 10s gap."""
    global GMAIL_PASS

    if not GMAIL_PASS:
        await update.message.reply_text(
            "⚠️ Gmail App Password not set!\nUse: `/setpass YOUR_APP_PASSWORD`",
            parse_mode="Markdown",
        )
        return

    chat = update.effective_chat
    if not chat:
        return

    existing_task = ctx.chat_data.get("bulk_task") if ctx.chat_data else None
    if existing_task and not existing_task.done():
        await update.message.reply_text(
            "⚠️ Bulk already running.\nUse `/cancelbulk` first.",
            parse_mode="Markdown",
        )
        return

    raw = update.message.text or ""
    # Remove command prefix (/bulk or /bulk@BotName) and parse remaining payload
    payload = re.sub(r"^/bulk(@\w+)?\s*", "", raw, flags=re.IGNORECASE).strip()
    if not payload:
        await update.message.reply_text(
            "❌ Usage:\n"
            "`/bulk hr@a.com hr@b.com`\n\n"
            "or multi-line:\n"
            "`/bulk`\n"
            "`hr@a.com`\n"
            "`hr@b.com`",
            parse_mode="Markdown",
        )
        return

    emails = extract_emails(payload)
    if not emails:
        await update.message.reply_text("❌ No valid emails found in your message.", parse_mode="Markdown")
        return

    await update.message.reply_text(
        f"🚀 Bulk started: `{len(emails)}` emails.\n"
        f"⏱ Gap: `10 seconds` between sends.\n"
        f"ℹ️ Duplicates will be skipped.",
        parse_mode="Markdown",
    )

    async def _run():
        sent_ok = 0
        skipped_dup = 0
        failed = 0

        for idx, to_email in enumerate(emails, start=1):
            # cancellation check
            if ctx.chat_data.get("bulk_cancel"):
                break

            domain = extract_domain(to_email)
            company = domain_to_company(domain)

            # Duplicate check
            existing = already_sent(domain)
            if existing:
                skipped_dup += 1
                await ctx.bot.send_message(
                    chat_id=chat.id,
                    text=(
                        f"⏭️ Skipped duplicate (`{idx}/{len(emails)}`)\n"
                        f"🏢 *{company}* (`{domain}`)\n"
                        f"📧 `{existing.get('email','')}`\n"
                        f"🕐 {existing.get('sent_at','')}"
                    ),
                    parse_mode="Markdown",
                )
                continue

            await ctx.bot.send_message(
                chat_id=chat.id,
                text=f"📨 Sending (`{idx}/{len(emails)}`) to *{company}* (`{to_email}`)...",
                parse_mode="Markdown",
            )

            result = await asyncio.to_thread(send_application_email, to_email, company, GMAIL_PASS)
            if isinstance(result, str) and result.startswith("✅"):
                sent_at = mark_sent(domain, to_email)
                sent_ok += 1

                await ctx.bot.send_message(
                    chat_id=chat.id,
                    text=f"{result}\n\n🏢 *{company}*\n📧 `{to_email}`",
                    parse_mode="Markdown",
                )

                if os.path.exists(CREDENTIALS_PATH):
                    ok, msg = await asyncio.to_thread(sync_sheet_upsert, domain, to_email, sent_at)
                    if not ok:
                        logger.warning("Sheet sync failed for %s: %s", domain, msg)

                # 10-second gap between actual sends
                if idx != len(emails):
                    await asyncio.sleep(10)
            else:
                failed += 1
                await ctx.bot.send_message(
                    chat_id=chat.id,
                    text=f"❌ Failed (`{idx}/{len(emails)}`) for `{to_email}`:\n`{result}`",
                    parse_mode="Markdown",
                )
                # still keep a small gap to avoid spam bursts
                if idx != len(emails):
                    await asyncio.sleep(2)

        canceled = bool(ctx.chat_data.get("bulk_cancel"))
        ctx.chat_data["bulk_cancel"] = False
        summary = (
            "🛑 Bulk canceled." if canceled else "✅ Bulk finished."
        ) + f"\n\n✅ Sent: `{sent_ok}`\n⏭️ Duplicates skipped: `{skipped_dup}`\n❌ Failed: `{failed}`"
        await ctx.bot.send_message(chat_id=chat.id, text=summary, parse_mode="Markdown")

    ctx.chat_data["bulk_cancel"] = False
    task = asyncio.create_task(_run())
    ctx.chat_data["bulk_task"] = task

async def cmd_cancelbulk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.chat_data:
        return
    task = ctx.chat_data.get("bulk_task")
    if not task or task.done():
        await update.message.reply_text("ℹ️ No bulk running.", parse_mode="Markdown")
        return
    ctx.chat_data["bulk_cancel"] = True
    await update.message.reply_text("🛑 Cancel requested. Bulk will stop soon.", parse_mode="Markdown")

async def cmd_checkbounces(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not get_sheet_webhook_url():
        await update.message.reply_text(
            "⚠️ Sheet not configured.\nPlace GCP credentials file in this folder or set SHEET_ID env var.",
            parse_mode="Markdown",
        )
        return
    if not GMAIL_PASS:
        await update.message.reply_text(
            "⚠️ Gmail App Password not set!\nUse: `/setpass YOUR_APP_PASSWORD`",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text("🔎 Checking Gmail bounces...", parse_mode="Markdown")
    found, updated = await asyncio.to_thread(check_gmail_bounces_and_update_sheet, True)
    await update.message.reply_text(
        f"✅ Done.\n\n📩 Bounces found: `{found}`\n🧾 Sheet updated: `{updated}`",
        parse_mode="Markdown",
    )

async def cmd_log(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    log = load_sent_log()
    if not log:
        await update.message.reply_text("📭 No mails sent yet.")
        return
    lines = ["📋 *Sent Mail Log:*\n"]
    for domain, info in log.items():
        lines.append(f"🏢 `{domain}`\n📧 {info['email']}\n🕐 {info['sent_at']}\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_clearlog(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    save_sent_log({})
    await update.message.reply_text("🗑️ Sent log cleared! You can re-send to all companies now.")

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Main handler – processes any message that looks like an email."""
    global GMAIL_PASS
    text = update.message.text.strip()

    # Check if it looks like an email
    if not is_valid_email(text):
        await update.message.reply_text(
            "🤔 That doesn't look like an email address.\n"
            "Send me something like: `hr@google.com`\n"
            "Or use /start to see all commands.",
            parse_mode="Markdown"
        )
        return

    to_email = text.lower()
    domain   = extract_domain(to_email)
    company  = domain_to_company(domain)

    # Check password set
    if not GMAIL_PASS:
        await update.message.reply_text(
            "⚠️ Gmail App Password not set!\nUse: `/setpass YOUR_APP_PASSWORD`",
            parse_mode="Markdown"
        )
        return

    # Duplicate check
    existing = already_sent(domain)
    if existing:
        keyboard = [
            [
                InlineKeyboardButton("✅ Send Anyway", callback_data=f"force|{to_email}|{company}"),
                InlineKeyboardButton("❌ Cancel",       callback_data="cancel"),
            ]
        ]
        markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"⚠️ *Duplicate Detected!*\n\n"
            f"Mail was already sent to *{company}* (`{domain}`).\n"
            f"📧 Email: `{existing['email']}`\n"
            f"🕐 Sent at: {existing['sent_at']}\n\n"
            f"Do you want to send again?",
            parse_mode="Markdown",
            reply_markup=markup
        )
        return

    # Send mail
    await update.message.reply_text(
        f"📨 Sending mail to *{company}* (`{to_email}`)...",
        parse_mode="Markdown"
    )
    result = send_application_email(to_email, company, GMAIL_PASS)
    sent_at = None
    if result.startswith("✅"):
        sent_at = mark_sent(domain, to_email)

    await update.message.reply_text(
        f"{result}\n\n"
        f"🏢 Company: *{company}*\n"
        f"📧 Sent to: `{to_email}`",
        parse_mode="Markdown"
    )

    if sent_at and os.path.exists(CREDENTIALS_PATH):
        def _sync_one():
            return sync_sheet_upsert(domain, to_email, sent_at)
        ok, msg = await asyncio.to_thread(_sync_one)
        if not ok:
            logger.warning("Sheet sync failed for %s: %s", domain, msg)

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handles inline button presses (force send / cancel)."""
    global GMAIL_PASS
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ Cancelled. Mail not sent.")
        return

    # force|email|company
    parts = query.data.split("|")
    if len(parts) == 3 and parts[0] == "force":
        _, to_email, company = parts
        domain = extract_domain(to_email)
        await query.edit_message_text(
            f"📨 Force sending to *{company}* (`{to_email}`)...",
            parse_mode="Markdown"
        )
        result = send_application_email(to_email, company, GMAIL_PASS)
        sent_at = None
        if result.startswith("✅"):
            sent_at = mark_sent(domain, to_email)
        await query.edit_message_text(
            f"{result}\n\n"
            f"🏢 Company: *{company}*\n"
            f"📧 Sent to: `{to_email}`",
            parse_mode="Markdown"
        )
        if sent_at and os.path.exists(CREDENTIALS_PATH):
            def _sync_one():
                return sync_sheet_upsert(domain, to_email, sent_at)
            ok, msg = await asyncio.to_thread(_sync_one)
            if not ok:
                logger.warning("Sheet sync failed for %s: %s", domain, msg)

# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    print("🚀 Starting Vishal's Job Mailer Bot...")
    print(f"📧 Gmail: {GMAIL_USER}")
    print(f"📄 Resume: {'Found ✅' if os.path.exists(RESUME_PATH) else 'NOT FOUND ❌ (place resume.pdf here)'}")
    print("-" * 50)

    async def _post_init(app: Application):
        async def _bounce_loop():
            while True:
                try:
                    # Only run when password + sheet webhook are configured.
                    if GMAIL_PASS and get_sheet_webhook_url():
                        await asyncio.to_thread(check_gmail_bounces_and_update_sheet)
                except Exception as e:
                    logger.warning("Bounce loop error: %s", e)
                await asyncio.sleep(43200)  # 12 hours (2 times per day)

        app.create_task(_bounce_loop(), name="bounce_loop")

    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("setpass",  cmd_setpass))
    app.add_handler(CommandHandler("setsheet", cmd_setsheet))
    app.add_handler(CommandHandler("setsecret", cmd_setsecret))
    app.add_handler(CommandHandler("sheetstatus", cmd_sheetstatus))
    app.add_handler(CommandHandler("syncsheet", cmd_syncsheet))
    app.add_handler(CommandHandler("bulk", cmd_bulk))
    app.add_handler(CommandHandler("cancelbulk", cmd_cancelbulk))
    app.add_handler(CommandHandler("checkbounces", cmd_checkbounces))
    app.add_handler(CommandHandler("log",      cmd_log))
    app.add_handler(CommandHandler("clearlog", cmd_clearlog))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
