# Phishing Signal Scanner — Chrome extension

Checks the email you're currently reading for phishing signals, and shows the
specific reason behind each flag.

**Everything runs inside the browser. There is no network call anywhere in this
extension** — no server, no API key, no telemetry. That is deliberate: a tool
that reads your email has no business uploading it.

---

## Install (unpacked, for development)

1. Open `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. Click **Load unpacked** and select this `extension/` folder
4. Open an email in Gmail and click the extension icon

## Using it

- **Scan the open email** reads the message currently on screen in Gmail.
- **Paste an email instead** works anywhere, and is the fallback if Gmail's
  layout changes.

Links are read from `href` attributes rather than the visible link text, so the
detector sees the real destination even when the display text hides it.

## What it checks

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
| `detector.js` | The detection logic. Pure functions, no DOM or network access. |
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
node extension/test/run_tests.js
```

`test/cases.json` holds a labeled set of emails together with the scores,
bands, and findings produced by the **Python** implementation. The test asserts
the JavaScript port matches all three exactly, on all 11 cases including edge
cases (empty input, no sender, matching sender/link domains). Any divergence
fails the build.

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
