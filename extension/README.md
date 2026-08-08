# Fraud & Phishing Scanner — Chrome extension

A local version of the web app. Two tabs:

- **Email** — checks the message you're reading in Gmail for phishing signals.
- **Document** — reads a PDF and cross-checks its printed dates against the
  file's own hidden metadata, the same way the web app does.

**Everything runs inside the browser. There is no network call anywhere in this
extension** — no server, no API key, no telemetry. That is deliberate: a tool
that reads your email has no business uploading it.

---

## Install (unpacked, for development)

1. Open `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. Click **Load unpacked** and select this `extension/` folder
4. **Pin it:** click the puzzle-piece icon in Chrome's toolbar, find
   "Fraud & Phishing Scanner", and click the pin. Without this the icon stays
   hidden in that menu and the extension looks like it did nothing.

## Using it

Open an email in Gmail and click the coral shield icon. **It scans
automatically when the popup opens** — no button press needed.

- **Scan again** re-reads the page after you switch messages.
- **Paste an email instead** works anywhere, and is the fallback if Gmail's
  layout changes. ⌘/Ctrl + Enter scans.

Note that the extension does not alter the Gmail page itself. Everything
appears in the popup.

Links are read from `href` attributes rather than the visible link text, so the
detector sees the real destination even when the display text hides it.

## Document tab

Drop in a PDF (or click to choose one). The extension reads the file **in the
browser** — no upload — and runs the same seven cross-checks as the web app:

| Check | Weight |
|---|---|
| Printed date older than the file's creation date | 35 |
| Editing software on a claimed original | 30 |
| Vendor absent from your approved list | 25 |
| Dated after the file was created | 20 |
| Metadata missing or stripped | 20 |
| Modified well after creation | 15 |
| Internal dates far apart | 10 |

You can supply a comma-separated approved-vendor list, matching the web app's
vendor check.

**How it reads a PDF without a library.** `pdfparse.js` pulls `/CreationDate`,
`/ModDate`, `/Producer` and `/Creator` straight out of the raw bytes, and
recovers the text layer by ASCII85-decoding and then inflating the content
streams with the browser's native `DecompressionStream`, before pulling string
literals out of the text-showing operators.

That works on ordinary generated PDFs. It does **not** work on scanned
documents or unusual encodings, and there is no OCR in the browser. When the
text layer can't be read the extension says so and still reports the metadata
findings, rather than scoring an empty document and reporting a falsely clean
result. A paste box is offered for the text in that case.

## What the email tab checks

| Signal | Weight |
|---|---|
| Asks for credentials or payment | 28 |
| Link points to a raw IP address | 28 |
| Pressure / urgency language | 22 |
| Shortened or hidden links | 16 |
| Links don't match the sender's domain | 12 |
| Insecure `http://` link | 10 |
| Generic greeting ("Dear customer") | 8 |

Scores cap at 100. **50+ is HIGH, 20+ is MEDIUM.**

These are heuristics and the tool is a decision aid, not a verdict. A low score
is not a guarantee that an email is safe.

## Files

| File | Role |
|---|---|
| `manifest.json` | Manifest V3 config. Permissions are limited to `activeTab`, `scripting`, and `mail.google.com`. |
| `detector.js` | Phishing detection logic. Pure functions, no DOM or network access. |
| `docdetector.js` | Document fraud logic — port of `evaluate()`, `find_dates()`, `parse_metadata_date()`. |
| `pdfparse.js` | Reads PDF metadata and text from raw bytes. No external library. |
| `content.js` | Pulls subject, sender, body, and link hrefs out of the Gmail page. |
| `popup.html` / `popup.js` | UI and rendering. |
| `test/` | Cross-language parity test. |

## Why the logic exists twice

The same rules live in Python (`app.py`, used by the web app) and in JavaScript
(`detector.js`, used here). The duplication is a deliberate trade: it's the
price of running detection locally instead of shipping people's email to a
server.

Two implementations of the same rules will drift apart unless something checks
them, so:

```bash
node extension/test/run_tests.js   # 34 cases: 11 email + 23 document
node extension/test/pdf_test.js    # the PDF reader vs. pypdf
```

`test/cases.json` and `test/doc_cases.json` hold labeled inputs together with
the scores, bands, and findings produced by the **Python** implementations —
the document set is the same one `eval/` scores the web app against, plus edge
cases for the date parser. The test asserts the JavaScript ports match all
three fields exactly across all 34 cases. Any divergence fails the build.

`pdf_test.js` goes further: it generates real PDFs with the app's own sample
generator, records what pypdf extracted, and checks the browser reader produces
the same metadata and arrives at the same risk score. It caught two genuine
bugs when first written — unstripped parentheses around metadata values, and
ASCII85-wrapped streams that made every text layer come back empty.

Regenerate the fixture after changing the Python detector:

```bash
python3 -c "
import sys, json; sys.path.insert(0,'.'); sys.path.insert(0,'eval')
import app
from dataset import EMAIL_CASES
cases = json.load(open('extension/test/cases.json'))
for c in cases:
    f, s = app.check_email(c['text'], c['sender'])
    c['expected_score'] = s
    c['expected_titles'] = [x['title'] for x in f]
    c['expected_band'] = app.risk_band(s)[0]
json.dump(cases, open('extension/test/cases.json','w'), indent=2)
print('regenerated', len(cases), 'cases')
"
```

## Privacy

- No network requests.
- No storage — nothing is written to disk or to `chrome.storage`.
- Host permission is restricted to `https://mail.google.com/*`.
- Email content is read into memory, scored, displayed, and discarded when the
  popup closes.

## Known limitations

- Gmail's DOM selectors are unofficial and can break without notice. The paste
  fallback exists for that reason.
- Detection is keyword and pattern based, so it has no view of email
  authentication headers (SPF, DKIM, DMARC), which is where a production tool
  would go next.
- Urgency keywords cannot distinguish manufactured urgency from a colleague who
  genuinely needs something today — see `legit_hard_urgent_real` in the test
  set, which scores 22 despite being legitimate.
