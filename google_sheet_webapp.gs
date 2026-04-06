/**
 * Google Apps Script Web App (Webhook)
 *
 * Goal:
 * - Bot pushes "sent" → Status = yes
 * - Later Gmail bounce arrives → Status becomes no (same domain row)
 *
 * Expected sheet columns (matches your screenshot):
 *   A: Domain
 *   B: Company
 *   C: Email
 *   D: Sent At
 *   E: Status  (validated values like: yes / no / rejected)
 *   F: Error   (optional)
 *
 * Security (optional but recommended):
 * - Script Property SECRET
 * - Requests must include JSON field: { "secret": "..." }
 *
 * Target sheet:
 * - Script Property TARGET_SHEET_NAME (optional)
 * - If not set, uses the first tab in the spreadsheet.
 */

var WEBHOOK_VERSION = "2026-04-03-v6";

function doPost(e) {
  try {
    var body = (e && e.postData && e.postData.contents) ? e.postData.contents : "";
    var data = body ? JSON.parse(body) : {};

    var secret = PropertiesService.getScriptProperties().getProperty("SECRET");
    if (secret && String(data.secret || "") !== String(secret)) {
      return _json(403, { ok: false, error: "forbidden", version: WEBHOOK_VERSION });
    }

    var action = String(data.action || "upsert").toLowerCase();
    var rows = Array.isArray(data.rows) ? data.rows : [];
    if (!rows.length) {
      return _json(400, { ok: false, error: "no_rows", version: WEBHOOK_VERSION });
    }

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = _getTargetSheet_(ss);

    // Detect header row. If A1 looks like "Domain", treat it as header and start from row 2.
    var headerA1 = String(sheet.getRange(1, 1).getValue() || "").trim().toLowerCase();
    var hasHeader = (headerA1 === "domain");
    var startRow = hasHeader ? 2 : 1;

    // Build existing domain -> row index map (col A).
    var lastRow = sheet.getLastRow();
    var domainToRow = {};
    if (lastRow >= startRow) {
      var domains = sheet.getRange(startRow, 1, lastRow - startRow + 1, 1).getValues();
      for (var r = 0; r < domains.length; r++) {
        var d = String(domains[r][0] || "").trim().toLowerCase();
        if (d && !domainToRow[d]) domainToRow[d] = r + startRow;
      }
    }

    var updated = 0;
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (!Array.isArray(row) || row.length < 2) continue;

      var domain = String(row[0] || "").trim().toLowerCase();
      if (!domain) continue;

      if (action === "set_status") {
        var status = String(row[1] || "").trim().toLowerCase(); // yes/no/rejected

        var targetRow = domainToRow[domain];
        if (!targetRow) {
          // Safety: do not create new rows during bounce updates.
          continue;
        }

        // E: Status only (dropdown)
        sheet.getRange(targetRow, 5, 1, 1).setValues([[status]]);
        updated += 1;
        continue;
      }

      // default: upsert
      // Payload can be:
      // - [domain, company, email, sent_at, status]
      // - [domain, email, sent_at, status] (company omitted)
      var company = "";
      var email = "";
      var sentAt = "";
      var statusUpsert = "yes";

      if (row.length >= 5) {
        company = String(row[1] || "").trim();
        email = String(row[2] || "").trim().toLowerCase();
        sentAt = String(row[3] || "").trim();
        statusUpsert = String(row[4] || "").trim().toLowerCase() || "yes";
      } else {
        email = row.length >= 2 ? String(row[1] || "").trim().toLowerCase() : "";
        sentAt = row.length >= 3 ? String(row[2] || "").trim() : "";
        statusUpsert = row.length >= 4 ? String(row[3] || "").trim().toLowerCase() : "yes";
      }

      var target = domainToRow[domain];
      if (target) {
        // Safety: avoid rewriting whole row; only refresh Email, Sent At, Status.
        sheet.getRange(target, 3, 1, 3).setValues([[email, sentAt, statusUpsert]]);
      } else {
        sheet.appendRow([domain, company, email, sentAt, statusUpsert]);
        domainToRow[domain] = sheet.getLastRow();
      }
      updated += 1;
    }

    return _json(200, {
      ok: true,
      version: WEBHOOK_VERSION,
      action: action,
      sheet: sheet.getName(),
      updated: updated
    });
  } catch (err) {
    return _json(500, { ok: false, error: String(err), version: WEBHOOK_VERSION });
  }
}

function doGet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = _getTargetSheet_(ss);
  return _json(200, {
    ok: true,
    message: "mailbot sheet webhook is running",
    version: WEBHOOK_VERSION,
    sheet: sheet.getName()
  });
}

function _getTargetSheet_(ss) {
  var name = PropertiesService.getScriptProperties().getProperty("TARGET_SHEET_NAME");
  if (name) {
    var s = ss.getSheetByName(name);
    if (s) return s;
  }
  return ss.getSheets()[0];
}

function _json(code, obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
