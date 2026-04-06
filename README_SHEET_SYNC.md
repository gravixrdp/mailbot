# Google Sheet sync (sent_log.json → Sheet)

Google Sheets API normally needs credentials. Easiest way (as you asked: “anyone can access”) is a **Google Apps Script Web App** webhook that your bot can POST to.

## 1) Create the webhook (Apps Script)

1. Open your sheet: `1-AUFpWgfJyuQLI3NxdE6mPtgl93-N87st4Emk0aGieY`
2. In the sheet: **Extensions → Apps Script**
3. Paste the code from `mailbot/google_sheet_webapp.gs`
4. (Optional but recommended) **Project Settings → Script properties**
   - Add `SECRET` = some random string
5. Deploy: **Deploy → New deployment → Web app**
   - Execute as: **Me**
   - Who has access: **Anyone**
6. Copy the Web App URL (ends with `/exec`)
7. After any code change: **Deploy → Manage deployments → Edit → Version → New version → Deploy**

Quick verify (browser): open your `/exec` URL and confirm it returns JSON with `version: "2026-04-03-v3"`.

## 2) Configure the bot

In Telegram:

- `/setsheet <YOUR_WEB_APP_URL>`
- (optional) `/setsecret <YOUR_SECRET>`
- `/setpass <YOUR_GMAIL_APP_PASSWORD>` (needed for bounce checking)
- `/syncsheet` (push all existing `sent_log.json`)

## 3) Auto-sync after every sent email

Run the bot with:

```bash
AUTO_SYNC_SHEET=1 python main.py
```

If the webhook is down, email sending still works; it just logs a warning.

## Where data goes

By default webhook writes into the **first tab** of your spreadsheet (so it works with your existing “yes/no/rejected” validations).

If you want a dedicated tab, set Apps Script **Script Property**:
- `TARGET_SHEET_NAME` = `Mailbot`

## Columns

No headers required. It writes:

1. Domain (col A)
2. Email (col B)
3. Sent At (col C)
4. Status (col D) → `yes` / `no` / `rejected`
5. Error (col E, optional; used for bounces)

## Bounce → auto mark NO

When Gmail later sends a bounce email (Mail Delivery Subsystem / Address not found), the bot checks bounces every 10 minutes and updates that domain’s **Status** to `no`.

Manual check anytime:
- `/checkbounces`
