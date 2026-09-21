# Google Sheets Setup (free)

This guide gets you a working "CRM" sheet + credentials in about 15 minutes.
Everything here is free with a normal Google account.

---

## 1. Create the sheet

1. Go to <https://sheets.google.com> and create a blank spreadsheet.
2. Rename it exactly to match `GOOGLE_SHEET_NAME` in your `.env`
   (default: **FixGenie Leads Master**).
3. You don't need to add headers by hand — the Python code creates the
   `Leads` and `Outreach Log` tabs with the correct columns on first run.
   (If you prefer to pre-create them, use the column order in
   `src/fixgenie/common/models.py` → `SHEET_COLUMNS`.)

---

## 2. Create a Google Cloud project + service account (for the Python route)

The Python pipeline authenticates as a **service account** (a robot Google
account), so it can write to the sheet unattended.

1. Open <https://console.cloud.google.com/> and create a new project
   (e.g. `fixgenie-outreach`).
2. In **APIs & Services → Library**, enable:
   - **Google Sheets API**
   - **Google Drive API** (needed for gspread to open the sheet by name)
3. Go to **APIs & Services → Credentials → Create Credentials → Service account**.
   - Give it a name like `fixgenie-bot`.
   - Skip the optional role/permission steps (click Done).
4. Open the new service account → **Keys → Add Key → Create new key → JSON**.
   - A `.json` file downloads. **This is your secret — never commit it.**
5. Move that file to `config/service_account.json` in this project
   (or point `GOOGLE_SERVICE_ACCOUNT_JSON` in `.env` at wherever you put it).

---

## 3. Share the sheet with the service account

1. Open `config/service_account.json` and copy the value of `"client_email"`
   (looks like `fixgenie-bot@fixgenie-outreach.iam.gserviceaccount.com`).
2. In your Google Sheet, click **Share** and add that email with **Editor**
   access.

That's it — the Python code can now read and write the sheet.

> **Security (Section 13):** the service account only has access to sheets you
> explicitly share with it, not your whole Drive. Keep it that way. Don't grant
> it Drive-wide scopes.

---

## 4. (Optional) Enable the Outreach Status dropdown

For clean, consistent data, add a data-validation dropdown on the
**Outreach Status** column (col N):

1. Select column N (from row 2 down).
2. **Data → Data validation → Add rule**.
3. Criteria: *Dropdown*, with values:
   `Not Contacted, Sent, Opened, Replied, Bounced, Unsubscribed, Send Failed`.

Do the same for **Email Verification Status** (col M):
`Valid, Risky, Invalid, Unknown`.

---

## 5. For the n8n route (OAuth instead of a service account)

n8n's native Google Sheets node uses OAuth2, not a service account:

1. In n8n, go to **Credentials → New → Google Sheets OAuth2 API**.
2. Follow n8n's built-in guide to create OAuth credentials in the same Google
   Cloud project (it walks you through the consent screen + client ID/secret).
3. Once connected, open each imported workflow and:
   - set the **Document ID** (`YOUR_SHEET_ID`) — it's the long string in your
     sheet's URL between `/d/` and `/edit`,
   - re-select the credential on every Google node,
   - set the `GOOGLE_PLACES_API_KEY` env var in your n8n instance.

---

## 6. (Optional) Apps Script backup trigger — zero server, fully free

If you want the auto-email behavior with **no server and no n8n at all**, paste
this into **Extensions → Apps Script** on the sheet. It sends a first email when
a row's status is `Not Contacted` and a valid email exists, then marks it `Sent`.

```javascript
// Time-driven trigger: run every 5-10 min (Triggers -> Add Trigger -> onNewLeads).
function onNewLeads() {
  const sh = SpreadsheetApp.getActive().getSheetByName('Leads');
  const data = sh.getDataRange().getValues();
  const header = data[0];
  const col = name => header.indexOf(name);

  const cEmail  = col('Email');
  const cStatus = col('Outreach Status');
  const cVerify = col('Email Verification Status');
  const cName   = col('Business Name');
  const cContact= col('Contact/Owner Name');
  const cLast   = col('Last Contacted Date');

  const CAP = 40;               // daily send cap (deliverability)
  let sent = 0;

  for (let r = 1; r < data.length && sent < CAP; r++) {
    const row = data[r];
    if (row[cStatus] !== 'Not Contacted') continue;
    if (row[cVerify] !== 'Valid') continue;
    if (!row[cEmail]) continue;

    const first = (row[cContact] || 'there').toString().split(' ')[0];
    const subject = 'Quick idea for ' + row[cName];
    const body =
      'Hi ' + first + ',\n\n' +
      'I came across ' + row[cName] + ' and wanted to reach out. I am with ' +
      'FixGenie Consulting Inc - we help local businesses automate repetitive ' +
      'manual work.\n\nOpen to a quick 10-minute call?\n\nBest,\nHarmeet\n\n' +
      '--\nFixGenie Consulting Inc\n123 Example St, Toronto, ON, Canada\n' +
      'Unsubscribe: https://fixgenie.co/unsubscribe?e=' + encodeURIComponent(row[cEmail]);

    GmailApp.sendEmail(row[cEmail], subject, body);

    sh.getRange(r + 1, cStatus + 1).setValue('Sent');
    sh.getRange(r + 1, cLast + 1).setValue(new Date().toISOString());
    sent++;
    Utilities.sleep(2000); // small gap between sends
  }
}
```

> Apps Script is the most "free" option (no VPS, no n8n hosting) but has the
> least control over dedup/validation. Use it as a lightweight backup or for a
> very small volume; use the Python pipeline as your main engine.
