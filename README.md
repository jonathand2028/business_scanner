# Commercial Proposal: Cross-Modal Data Inconsistency Detection

A business tool that catches fake documents and images by checking whether a file's different parts agree with each other, instead of trying to guess whether AI made it.

**Owner:** Jonathan Dong
**Last updated:** June 22, 2026

---

## Executive Summary

Companies have to trust a constant stream of documents and images: vendor invoices, identity photos, receipts, and scanned records. Cheap, powerful AI has made convincing fakes easy to produce in bulk, and the usual defenses (a person reviewing files, or simple software rules) can no longer keep up.

The obvious idea is to ask "was this made by AI?" That is a weak approach. Detecting AI by its fingerprints is unreliable, throws a lot of false alarms, and loses a constant arms race against better AI generators. This product does something different. It treats fraud as a consistency problem. To fake a document well, a forger has to keep all of its separate parts in agreement, and they usually slip up. The tool pulls each part out and checks them against each other. An invoice that says "January 2026" but whose hidden file data shows it was saved from Photoshop in June 2026 gets caught by simple data work, not by an AI guessing game.

The product is a website where you upload a file and get back a report. There is nothing to install. The first customers are financial apps, digital insurance companies, and corporate purchasing teams.

---

## 1. What the Product Is

It is a fraud checker for businesses that looks at several parts of a file at once: the text you can read, the image itself, and the hidden information attached to the file (called metadata, which records things like when a file was made and what software made it).

The real value is checking whether a document's facts line up, not claiming to magically spot AI. The tool catches logical lies that a busy human reviewer would miss: a date that does not match when the file was actually created, a supplier that does not exist in the company's records, editing-software traces on a file that is supposed to be an untouched original, or numbers that do not add up. Each of these is a clear, provable problem that a fraud analyst can act on.

The main targets are forged supplier invoices, fake or altered ID documents, and doctored receipts and company records.

---

## 2. Why Now (2026)

A few years ago, making a convincing fake invoice or a realistic photo of an ID took skill, time, and money. That kept this kind of fraud rare and usually sloppy. AI removed all three barriers. Today a fraudster can produce an invoice that copies a real supplier's layout, an ID photo that passes an automatic identity check, or a cleanly edited receipt in minutes, for almost nothing, and in large numbers.

That breaks the two things companies rely on. A person reviewing files cannot match the volume or spot the quality anymore. Older software was built to check business facts (like "does this invoice number exist?"), not to ask whether the file itself is genuine.

Here is the key insight. Chasing the AI generator is the wrong fight, because generators improve faster than detectors do. The fight you can actually win is consistency. No matter how good a fake looks, the forger still has to make the visible text, the hidden file data, and the real business facts all agree at the same time, and that is very hard to pull off on every level at once. That gap is the product.

---

## 3. How It Works

A file goes through two steps that pull information out of it, and then a final step that compares everything. Every step uses standard, well-known tools, nothing exotic.

### Step 1: Text and spreadsheet files (CSV, log, PDF)

- Pull out the text and structure using common Python tools (`pypdf` for PDFs, standard parsing for spreadsheets and logs).
- Read the hidden file data (author, creation and edit dates, and the software that made it) using `pypdf` and a tool called `ExifTool`.
- Check that the file makes sense on its own: do the line items add up to the total, are the dates and reference numbers reasonable, does the layout match that supplier's normal format.

### Step 2: Images and scans (JPG, PNG)

- Read the text printed inside the image using OCR, which is technology that pulls written words out of a picture (like how your phone can copy text from a photo). Good options are Tesseract OCR or AWS Textract.
- Read the hidden file data with ExifTool and a Python tool called Pillow. This recovers the creation time and the software used. For example, a "Photoshop" tag on a file that is supposed to be an original scan is a red flag.
- Run a few simple, well-understood image checks that reveal where a picture was edited or pasted together, such as breaks in the photo's compression texture.

### Step 3: The cross-check (the heart of the product)

Now the tool compares everything it pulled out, against each other and against what the company already knows:

- Does the visible text agree with the hidden file data? For example, does the printed date match the file's real creation date and the software used?
- Does the visible text agree with the company's records? For example, is this a known, approved supplier, and does the amount fit past invoices?
- Does the image contradict itself? For example, does its edit history clash with its claim to be an untouched original?

Each problem it finds comes with the exact evidence, a confidence level, and a plain explanation. A worked example: a receipt image reads "March 3, 2026," but the file data shows the image was created on June 10, 2026 and was saved from a photo editor, and the store name matches no supplier on file. Any one clue might slip by, but together they prove fraud with solid evidence.

```
  CSV / log / PDF  ->  pypdf, ExifTool ----------------+
                                                        |--> CROSS-CHECK --> Report:
  JPG / PNG / scan ->  Tesseract or Textract (OCR),     |     (text vs. file    - list of problems
                        ExifTool, Pillow (file data) ---+      data vs. company  - evidence + confidence
                                                               records)
```

---

## 4. Who Buys It and Why It Helps Right Away

The customers are businesses that receive lots of documents and images they are forced to trust:

- **Financial apps (FinTech):** they verify identities and move money, so a fake ID is a direct loss.
- **Digital insurance companies:** claims come in as photos and receipts, so edited damage photos and fake receipts lead to paying out on fraud.
- **Corporate purchasing teams:** they pay company bills and are the main target of fake supplier invoices.

It helps on day one because there is nothing to set up. "Integration," meaning wiring a tool into a company's existing systems, is usually a slow, expensive engineering project that needs IT approval, and it is the main reason new tools die before they prove their worth. This product skips all of that. It is a website: upload a file or a batch, get a report. A purchasing analyst can start checking suspicious invoices the same afternoon. For customers who later want automatic, behind-the-scenes scanning, that can be added, but it is never required to get value.

---

## 5. Risks and How I Handle Them

### Risk 1: The arms race against better AI

AI generators keep getting better, so any detector that depends on spotting the generator will fade over time.

How I handle it: the product does not lead with AI-spotting. The backbone is the consistency check, which does not care how good the fake looks. A perfect-looking image still has to survive the file-data and business-record checks. Any AI-spotting signals are kept as optional, clearly labeled, low-importance hints. The AI parts are kept separate from the main logic so they can be replaced or retrained without rebuilding the tool.

### Risk 2: False alarms that lock out honest people

Wrongly flagging a real invoice or a real customer's ID wastes time and can block a paying customer.

How I handle it: every result comes with a confidence score and the specific evidence, never just a "fake" stamp. Flagged items go to a person to review instead of being auto-rejected. Each customer can set how strict it is, since verifying identities needs to catch more than screening invoices does. And every time an analyst confirms or clears a flag, the tool tunes itself to make fewer mistakes next time.

### Risk 3: Bad inputs

OCR and file-data reading can fail on blurry scans or files that have had their hidden data stripped out.

How I handle it: treat weak extraction as its own warning sign (a file with its hidden data wiped is itself suspicious), fall back to AWS Textract for hard scans, and always show how confident the extraction was so an analyst knows how much to trust the result.
