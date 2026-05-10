# Upload forge-shield to PyPI — step-by-step (first time)

Estimated time: 15 minutes including 2FA setup.

You'll need:
- Your phone (for the 2FA app)
- Your email open in another tab
- A safe place to save a token (password manager ideal)

---

## STEP 0 — Install a 2FA app on your phone (if not already done)

PyPI requires 2FA (two-factor authentication) since 2024.
Install ONE of these on your phone — pick whichever:

- **Aegis** (Android, FOSS) — recommended
- **Google Authenticator** (Android/iOS)
- **1Password** / **Bitwarden** (if you already use them)

Open the app once so it's ready. We'll scan a QR code from PyPI's site.

---

## STEP 1 — Sign up on TestPyPI first (sandbox, ~5 min)

**Why TestPyPI before the real PyPI**: TestPyPI is the practice ground.
If you mess up the upload, the real PyPI doesn't get polluted, and you
can't re-upload the same version (PyPI is immutable per version).

### 1.1 — Open https://test.pypi.org/account/register/

Fill in:
- Username: `sky1241` (or whatever you want — same as GitHub recommended)
- Password: a strong one
- Email: your real email

Click **"Create account"**.

### 1.2 — Verify your email

Open your email. Click the verification link from `noreply@pypi.org`.
You're now logged in.

### 1.3 — Set up 2FA (mandatory)

Top right → click your username → **Account settings**.

Scroll down to **"Two-factor authentication (2FA)"**.

Click **"Add 2FA with authentication application"**.

A QR code appears. Open Aegis (or whatever app) on your phone:
- Tap "+" or "Add account"
- Scan the QR code
- The app shows a 6-digit code that refreshes every 30s

Type the 6-digit code into the PyPI field. Click **"Verify"**.

PyPI shows you **8 recovery codes**. Click **"Generate codes"** if needed.
**Save these somewhere safe** (password manager, encrypted note). They're
your backup if you lose your phone.

### 1.4 — Create an API token

Still in **Account settings**, scroll to **"API tokens"**.

Click **"Add API token"**.
- Token name: `forge-shield-upload` (whatever)
- Scope: **"Entire account (all projects)"** (for this first upload)

Click **"Create token"**.

**A token starting with `pypi-AgEI...` shows up. Copy it NOW.**
**It's shown only ONCE. If you close the page, it's gone.**

Save it somewhere safe. We'll use it in step 4.

---

## STEP 2 — Test upload on TestPyPI

In your terminal:

```bash
cd /home/sky/Bureau/forge
.venv/bin/python -m pip install twine --quiet
.venv/bin/python -m twine upload --repository testpypi dist/forge_shield-1.2.2*.{tar.gz,whl}
```

When prompted:
- **Username**: `__token__` (literally type the underscores and the word `token`)
- **Password**: paste the token you saved (starts with `pypi-AgEI...`)

Should take ~10 seconds. Output:

```
Uploading forge_shield-1.2.2-py3-none-any.whl
100%
Uploading forge_shield-1.2.2.tar.gz
100%

View at:
https://test.pypi.org/project/forge-shield/1.2.2/
```

### 2.1 — Verify the test upload worked

Open the URL in your browser. You should see the project page with:
- Version 1.2.2
- README rendered (check for any markdown rendering issues)
- "pip install -i https://test.pypi.org/simple/ forge-shield" command

If the README looks good and the page loads, you're ready for the real upload.

---

## STEP 3 — Sign up on the REAL PyPI

Same process as TestPyPI but on the production site.

### 3.1 — https://pypi.org/account/register/

**Note**: PyPI and TestPyPI accounts are SEPARATE. You need a fresh
account on pypi.org even if you used the same username on TestPyPI.

Same steps as 1.1 → 1.2 → 1.3 → 1.4. The 2FA QR code is different
(another entry in your authenticator app).

### 3.2 — Get a PyPI API token

Same as 1.4 but on pypi.org this time. Save the new token (starts with
`pypi-AgEI...` again, but it's a different token).

---

## STEP 4 — Upload to the REAL PyPI

```bash
cd /home/sky/Bureau/forge
.venv/bin/python -m twine upload dist/forge_shield-1.2.2*.{tar.gz,whl}
```

Same prompts:
- **Username**: `__token__`
- **Password**: the **PyPI** token (not the TestPyPI one)

Output:

```
Uploading forge_shield-1.2.2-py3-none-any.whl
100%
Uploading forge_shield-1.2.2.tar.gz
100%

View at:
https://pypi.org/project/forge-shield/1.2.2/
```

### 4.1 — Verify

Open the URL. You should see:
- forge-shield 1.2.2 page on the REAL PyPI
- README rendered
- `pip install forge-shield` command in the install instructions

### 4.2 — Test pip install from anywhere

In a fresh terminal (or even on another machine):

```bash
python3 -m venv /tmp/test-pypi-install
/tmp/test-pypi-install/bin/pip install forge-shield
/tmp/test-pypi-install/bin/forge --version
```

Should print:

```
forge-shield 1.2.2
```

**🎉 Production confirmed.** The "raccord au tableau électrique" is done.

---

## STEP 5 — Save the token in `~/.pypirc` for future uploads

So you don't have to copy-paste the token every release:

```bash
cat > ~/.pypirc <<'EOF'
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-AgEI...PASTE-YOUR-PYPI-TOKEN-HERE...

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-AgEI...PASTE-YOUR-TESTPYPI-TOKEN-HERE...
EOF
chmod 600 ~/.pypirc
```

Replace the two `PASTE-YOUR-...` placeholders with the real tokens.
The `chmod 600` makes the file readable only by you.

For all future uploads it'll be one command:

```bash
.venv/bin/python -m twine upload dist/forge_shield-X.Y.Z*.{tar.gz,whl}
```

No more username/password prompts.

---

## Common gotchas

- **"forge-shield already exists" error** → that name is taken on PyPI by
  someone else. You'll need to pick a different name (`forge-shield-py`,
  `pyforge`, etc.) and update `pyproject.toml` → `name = "..."` then rebuild.
- **"version already exists"** → PyPI is immutable per version. You can
  never re-upload the same version. Bump (1.2.2 → 1.2.3) and re-upload.
- **README renders badly** → mostly the same as GitHub but `<details>`
  collapsibles aren't supported. Check on TestPyPI before the real upload.
- **Lost the token** → just create a new one in your PyPI account settings.
  Tokens can be revoked there too.

---

## What happens after upload

- `pip install forge-shield` works for anyone in the world
- The PyPI page links back to https://github.com/sky1241/forge (per `pyproject.toml`)
- Subsequent releases: bump version, build, upload (all one command if `.pypirc` is set)
- Forge becomes a "real" Python package at this point.

---

## When you're ready

Open this guide in another tab. Open https://test.pypi.org/account/register/
in another tab. Phone with 2FA app open. Email tab open. Go.
