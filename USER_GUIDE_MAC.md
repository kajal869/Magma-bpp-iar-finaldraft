# Magma Policy Draft Studio: user guide for Mac

This guide takes you from a clean Mac to a working demo in your browser. No coding is needed; you copy and paste a few commands into Terminal.

The portal reads two Excel files (a closing slip and a quote), shows which mandatory fields were captured and which are missing, lets you fill them in, and gives you the policy **front pack** as a PDF. Nothing is stored: uploaded files are deleted as soon as they are read, and the PDF is kept only in memory for 15 minutes.

> **Demo mode.** This version only knows one fictional company, ACME Precision Products. It does not yet extract data from real quotes. Use the sample files in the `samples` folder.

---

## 1. What you need (one time)

| Item | How to check | How to get it |
|---|---|---|
| macOS 12 (Monterey) or newer, Intel or Apple Silicon | Apple menu > About This Mac | - |
| Terminal | Press `Cmd + Space`, type **Terminal**, press Enter | Built in |
| Python 3.10 or newer | `python3 --version` | `brew install python` or https://www.python.org/downloads/ |
| Node.js 18 or newer | `node --version` | `brew install node` or https://nodejs.org (LTS) |
| Git | `git --version` | `xcode-select --install` (accept the prompt) |

If you do not have Homebrew and want it: paste the one-line installer from https://brew.sh into Terminal. It is optional; the downloads from python.org and nodejs.org work too.

**Recommended font (for PDFs that look like the Magma originals):** the policy uses Calibri, which is not on a Mac unless Microsoft Office is installed. Without it the PDF falls back to another font and pages may reflow slightly. Fix it with one command:

```bash
brew install --cask font-carlito
```

Carlito is a free font with the same letter widths as Calibri.

---

## 2. Get the code

In Terminal:

```bash
cd ~/Documents
git clone https://github.com/kajal869/Magma-bpp-iar-finaldraft.git
cd Magma-bpp-iar-finaldraft
```

The repository is private. If Git asks for a login, use your GitHub account (a personal access token instead of a password, or sign in through GitHub Desktop / `gh auth login`).

---

## 3. Start the portal (easy way)

From inside the `Magma-bpp-iar-finaldraft` folder:

```bash
chmod +x run_demo.sh
./run_demo.sh
```

The first run takes a few minutes. It will:
1. create a private Python environment in a hidden `.venv` folder and install the Python packages;
2. download a headless Chromium browser used to draw the PDF (about 150 MB, once);
3. install and build the web app (needs internet, once);
4. start the server and open **http://localhost:8000** in your browser.

Later runs start in a few seconds. Leave the Terminal window open while you use the portal. To stop it, click the Terminal window and press `Ctrl + C`.

---

## 4. Use the portal

1. **Upload the two files.** Drag them onto the cards, or click a card to browse. Use the samples: `samples/demo_closing_slip.xlsx` (closing slip) and `samples/demo_quote.xlsx` (quote). Click **Read the files**.
2. **Wait a few seconds** while the progress screen runs through its steps.
3. **Review the fields.** The ring at the top shows how many mandatory fields are captured. Each field is marked:
   - green **Captured**: found in your files (or from the verified demo data);
   - amber **Check**: the closing slip says something different; both values are shown;
   - red **Missing**: not found. Policy-system values (policy number, issue date, servicing office, Magma GSTIN, GST invoice number and date, place of supply, stamp duty) are never in the two files, so they start empty.
4. **Fill what is missing.** Type values in, or click **Use sample: ...** next to a field, or **Fill missing with sample values** to fill them all. You can edit any field.
5. Click **Generate front pack**.
   - If mandatory fields are still empty, a window lists them and warns that **those places will be left blank** in the PDF. Choose **Go back and fill** or **Generate with blanks**.
6. **Preview and download.** Scroll through the pages on the right, then click **Download PDF**. **Edit fields** takes you back to change values; **Start over** clears everything.

The file name looks like `Front pack - <Insured> - <Policy number>.pdf` (it says `no-policy-no` when the policy number was left blank).

---

## 5. Start it by hand (if the script does not work)

```bash
cd ~/Documents/Magma-bpp-iar-finaldraft

# Python side, once
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# Web side, once
cd web
npm install
npm run build
cd ..

# Start the portal (every time; run "source .venv/bin/activate" first in a new Terminal window)
python -m uvicorn --app-dir server main:app --port 8000
```

Then open http://localhost:8000. To change the web screens while the server runs, open a second Terminal, run `cd web && npm run dev` and use http://localhost:5173 instead.

**After you update the code** (`git pull`), rebuild the web app: `cd web && npm install && npm run build`.

---

## 6. Check that everything works (optional)

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest server/tests -q
```

You should see `9 passed`.

---

## 7. Troubleshooting

| Problem | What to do |
|---|---|
| `command not found: python3` / `node` | Install them as in section 1, then open a new Terminal window. |
| `externally-managed-environment` when running `pip` | You skipped the virtual environment. Run `python3 -m venv .venv` and `source .venv/bin/activate` first (the script does this for you). |
| `Executable doesn't exist ... playwright` or the PDF step fails | Run `source .venv/bin/activate` then `python -m playwright install chromium`. |
| Page says it cannot reach the server | The server is not running or is on another port. Start it again (section 3 or 5) and open http://localhost:8000. |
| `Address already in use` on port 8000 | Something else uses the port. Find it with `lsof -i :8000`, stop it with `kill <PID>`, or start on another port: `python -m uvicorn --app-dir server main:app --port 8001` and open http://localhost:8001. |
| `npm install` fails with permission errors (`EACCES`) | Do not use `sudo`. Fix npm's folder ownership (`sudo chown -R $(whoami) ~/.npm`) and run it again. |
| "This case isn't supported in the demo yet" | The closing slip is not the ACME demo company. Use the files in `samples/`. Real extraction is not connected yet. |
| A yellow warning says the quote seems to be for another insured | The quote file does not mention the same company as the closing slip. Check you picked the matching pair. |
| PDF text looks different from the Magma originals | Install the Carlito font (section 1) and generate again. |
| Browser shows an old version after an update | Hard-refresh: `Cmd + Shift + R`. |
| Everything is stuck | Press `Ctrl + C` in Terminal, then start again. Nothing is saved, so you lose nothing. |

---

## 8. Privacy and limits

- Files you upload are written to a temporary folder for the few seconds it takes to read them, then deleted. There is no database and nothing is uploaded to the internet; the portal runs on your Mac.
- Generated PDFs live in memory for 15 minutes or until you click **Start over**.
- Output is the front pack only (schedule, premium summary, GST block and annexures), not the full policy wording.
- This is an internal demo. Do not use its output as an issued policy.
