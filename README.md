# Penguinly

A small-circle social platform for tight-knit communities. Think intimate group chats, a public square feed, direct messages, and profiles — built for 6–19 people per group.

**Live site:** `http://34.234.4.250` (AWS Lightsail, Amazon Linux 2023)

---

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.9 · Flask 3.0 · Flask-Login · Flask-SQLAlchemy |
| Database | SQLite (dev + prod) · PostgreSQL-ready |
| Auth | Werkzeug password hashing · session-based login |
| Frontend | Vanilla JS · EasyMDE (markdown editor) |
| Serving | gunicorn (3 workers) · nginx reverse proxy |
| Hosting | AWS Lightsail (`ec2-user@34.234.4.250`) |

---

## Features

### Social
- **Public square** — global feed with posts, reactions (like/heart), comments, image uploads
- **Groups** — invite-only rooms (6–19 members), real-time-polled group chat with reactions
- **Direct messages** — 1:1 DM threads with AJAX polling
- **Profiles** — bio, avatar color, follow/unfollow, follower counts
- **Notifications** — @mentions, reactions, comments, follows, group invites
- **#hashtags & @mentions** — clickable inline links, live autocomplete dropdown, hashtag feed pages (`/tag/<name>`)

### Posts
- Plain text or **Markdown mode** (EasyMDE editor, per-user toggle in Settings)
- Image uploads (jpg/png/gif/webp, up to 16MB, UUID-named in `static/uploads/`)
- Edit and delete own comments; post authors and admins can delete posts

### Themes
Three CSS themes selectable in Settings, persisted in `localStorage` and the DB:
- **Penguin Sunset** (default) — purple/indigo accent
- **Natural** — earth tones
- **B&W** — monochrome

### Admin (username `penguin` only)
The `penguin` account is the superadmin. Accessible at `/admin`:
- View all users with bot-score badges
- **Reset password** — generates a temp password shown once in a flash message
- **Flag for CAPTCHA** — user must solve a math challenge on next login
- **Ban / Unban** — banned users are immediately logged out on any request
- **Delete user** — cascades to posts, comments, DMs, notifications, follows, group memberships

### Bot detection
`forms.py` scores every username at registration (0–100) using:
- Shannon entropy (high = random-looking)
- Regex patterns (`user123456`, pure digits, no vowels, repeating chars, etc.)
- Suspicious word list
- Digit ratio, trailing digits, length

Scores ≥ 70 block registration. The admin panel displays the score for every existing user.

---

## Project Structure

```
penguinly/
├── app.py               # All routes and business logic
├── models.py            # SQLAlchemy models
├── forms.py             # WTForms + bot-score heuristics
├── config.py            # Dev / production config classes
├── wsgi.py              # gunicorn entrypoint
├── requirements.txt
├── .env.example         # Copy to .env and fill in
├── nginx.conf           # nginx site config
├── penguinly.service    # systemd unit file
├── static/
│   ├── css/style.css    # All styles (Crystal design system)
│   ├── js/main.js       # Theme init, sidebar, autocomplete, AJAX polling
│   └── uploads/         # User-uploaded images (gitignored except .gitkeep)
└── templates/
    ├── base.html         # Shell: sidebar, nav, theme/font links
    ├── square.html       # Public feed
    ├── settings.html     # Theme picker, article mode, account links
    ├── tag.html          # Hashtag feed (/tag/<name>)
    ├── admin/
    │   └── panel.html    # Superadmin user management table
    ├── auth/
    │   ├── login.html    # Login + math CAPTCHA challenge step
    │   └── register.html
    ├── groups/
    │   ├── index.html
    │   ├── create.html
    │   └── view.html     # Group chat with AJAX polling
    ├── dm/
    │   └── index.html    # DM list + thread with AJAX polling
    ├── profile/
    │   ├── view.html
    │   └── edit.html
    └── notifications.html
```

---

## Database Models

| Model | Key fields |
|---|---|
| `User` | username, email, password_hash, avatar_color, theme, article_mode, is_admin, needs_captcha, is_banned |
| `Post` | content, post_type (public/group), image_filename, is_markdown |
| `Comment` | content, updated_at |
| `Follow` | follower_id → following_id (unique pair) |
| `Group` | name, max_members (default 19), is_private, cover_color |
| `GroupMembership` | role (admin/member), status (active/invited) |
| `GroupMessage` | content, reactions via `MessageReaction` |
| `DirectMessage` | sender_id, receiver_id, is_read |
| `Notification` | type, message, related_id, is_read |
| `PostReaction` / `MessageReaction` | reaction_type (like/heart) |

---

## Local Development

### 1. Clone and set up

```bash
git clone https://github.com/osoliman/penguinly.git
cd penguinly
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set SECRET_KEY
```

### 3. Initialize the database

```bash
flask --app app migrate-db
```

This runs idempotent `ALTER TABLE` migrations. Safe to re-run.

### 4. Run

```bash
flask --app app run --debug
```

Site is at `http://localhost:5000`.

### 5. Create the superadmin account

Register normally with username **`penguin`**. That account automatically gets the Admin nav link and full superadmin powers.

---

## Deployment (AWS Lightsail)

**Server:** Amazon Linux 2023 · `ec2-user@34.234.4.250`  
**SSH key:** `OneDrive/penguinly/LightsailDefaultKey-us-east-1.pem`

### One-liner deploy

```bash
ssh -i "~/path/to/LightsailDefaultKey-us-east-1.pem" ec2-user@34.234.4.250 \
  'cd /home/ec2-user/penguinly && git pull && source venv/bin/activate && pip install -r requirements.txt -q && flask --app app migrate-db && sudo systemctl restart penguinly'
```

### First-time server setup

```bash
# Install dependencies
sudo dnf install -y python3 python3-pip nginx git

# Clone repo
cd /home/ec2-user
git clone https://github.com/osoliman/penguinly.git
cd penguinly

# Virtualenv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Environment
cp .env.example .env
# Set SECRET_KEY and FLASK_ENV=production in .env

# Database
flask --app app migrate-db

# Nginx
sudo cp nginx.conf /etc/nginx/conf.d/penguinly.conf
# Edit nginx.conf: change alias path from /home/ubuntu/ to /home/ec2-user/
sudo nginx -t && sudo systemctl restart nginx

# systemd service
sudo cp penguinly.service /etc/systemd/system/
# Edit penguinly.service: change User/Group/paths from ubuntu to ec2-user
sudo mkdir -p /var/log/penguinly
sudo systemctl daemon-reload
sudo systemctl enable --now penguinly
```

### Useful server commands

```bash
# Check app status
sudo systemctl status penguinly

# View live logs
sudo journalctl -u penguinly -f

# Restart app
sudo systemctl restart penguinly

# Check nginx
sudo systemctl status nginx
sudo nginx -t
```

---

## Key Conventions

- **Push directly to `main`** — solo project, no PRs needed
- **Migrations** are hand-written `ALTER TABLE` statements in the `migrate-db` CLI command in `app.py`. Each is wrapped in try/except so re-running is safe.
- **Uploads** are stored as `{uuid}.{ext}` in `static/uploads/`. The folder is gitignored (only `.gitkeep` is tracked).
- **No CSRF tokens** — Flask-WTF is imported for bot detection only; `CSRFProtect` is not initialized. Don't add `{{ csrf_token() }}` to forms.
- **Theme** is applied via `data-theme` on `<html>`. An inline `<script>` in `<head>` reads `localStorage` before CSS loads to prevent flicker.
- **Superadmin** is detected by `current_user.username == 'penguin'` — no DB flag needed.
- **AJAX polling** for group chat and DMs uses `setInterval` at ~2s. Endpoints: `/api/groups/<id>/messages` and `/api/dm/<id>/messages`.
