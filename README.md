# Campus & City Safe-Route Navigator — Backend

Flask REST API backed by SQLite. The `waywise.db` database and its tables are created automatically when `app.py` starts. The database file stays in this folder and records persist between restarts.

## Run locally

```bash
python -m pip install -r requirements.txt
python app.py
```

The backend listens at `http://127.0.0.1:5000`.

## API endpoints

- `GET /api/health` — check API/database status
- `POST /api/users` — create a user profile
- `GET /api/users/<id>` — retrieve one user profile
- `POST /api/hazards` — store a hazard report
- `GET /api/hazards` — list hazard reports
- `POST /api/feedback` — store feedback

### Example user registration

```bash
curl -X POST http://127.0.0.1:5000/api/users \
  -H "Content-Type: application/json" \
  -d '{"full_name":"Test User","email":"test@example.com","phone":"9876543210"}'
```

### Example feedback (optionally linked to a registered user)

```bash
curl -X POST http://127.0.0.1:5000/api/feedback \
  -H "Content-Type: application/json" \
  -d '{"user_id":1,"category":"Suggestion","rating":5,"message":"Easy to use"}'
```

### Example hazard report

```bash
curl -X POST http://127.0.0.1:5000/api/hazards \
  -H "Content-Type: application/json" \
  -d '{"user_id":1,"type":"Poor lighting","description":"Dark near the east gate","lat":16.5062,"lon":80.6480}'
```

## Database tables

- `users`: profile/contact details and registration timestamp
- `hazard_reports`: hazard category, description, map coordinates, optional reporter user ID
- `user_feedback`: category, 1–5 rating, message, optional user ID

Use a SQLite viewer in VS Code to open `waywise.db` after running the app.

## Important security note

This is a local development/demo backend, not production authentication. It stores profile data but does not implement passwords, login, roles, or protected admin access. Do not expose it to the public internet without adding authentication, authorization, HTTPS, privacy safeguards, and production deployment configuration. Do not store passwords as plain text.


## Website chatbot
A floating **Ask WayWise** chat widget is included in the website. It sends messages to `POST /api/chat` and uses a contextual built-in responder and can optionally use a server-configured AI provider. It does not require an API key for basic answers. The assistant is a demo and is not an emergency dispatch service.


## Voice assistant
The WayWise chat widget supports browser voice input and spoken replies. Open the chat and tap the microphone to dictate a question; assistant replies are read aloud while **Voice on** is enabled. Voice input uses the browser Web Speech API and is best supported in Chrome/Edge. Your browser may ask for microphone permission, and voice recognition may require an internet connection. If voice input is unavailable, type into the chat box. Spoken replies use the browser's built-in speech synthesis.


## Login and account storage

The website has a login and registration screen. Create an account using a username, email address, and password (minimum 8 characters). Usernames, email addresses, and **password hashes** are stored in the SQLite database file `waywise.db`, in the `auth_accounts` table. Raw passwords are never saved. Email addresses and usernames must be unique. Existing databases are migrated automatically when the app starts. Do not open or share the database as if it were a plain-text password list.

For deployment, set a long random `WAYWISE_SECRET_KEY` environment variable before starting Flask so login sessions remain secure across restarts. This is a learning/demo project; before public deployment, add HTTPS, rate limiting, CSRF protection, backups, and a production WSGI server.

## Administrator, email OTP, and temporary account suspension

### Administrator account

On first startup, the backend creates the administrator account if one does not already exist:

- Username: `ADMIN`
- Initial password: `ADMIN1234`

Sign in from the website login screen with those credentials. The site redirects the administrator to `/admin`. The dashboard lists registered usernames, email addresses, account creation dates, verification status, and allows the administrator to disable a user for a chosen number of hours (1–8760) or re-enable them.

**Change the initial admin password before hosting the site publicly.** Set `WAYWISE_ADMIN_PASSWORD` in `.env` before the first startup. If the admin account has already been created, changing that environment value does not automatically overwrite the existing password; use the normal password reset only for user accounts, and implement/change the admin password separately before deployment.

### Email verification and password reset

Registration sends a six-digit OTP to the email address. The code expires after 10 minutes and is limited to five attempts. The Forgot password flow sends a similar code to the registered email before updating the password hash. Email sending requires SMTP credentials; without these settings, account registration and password reset will return an email-configuration error.

1. Copy `.env.example` to a file named `.env` in this folder.
2. Fill in `WAYWISE_SMTP_HOST`, `WAYWISE_SMTP_PORT`, `WAYWISE_SMTP_USER`, `WAYWISE_SMTP_PASSWORD`, and `WAYWISE_SMTP_FROM` for your mail provider. For Gmail, use a Google App Password, not your normal Gmail password.
3. Replace `WAYWISE_SECRET_KEY` with a long random value. Configure `WAYWISE_ADMIN_PASSWORD` before the first run.
4. Install dependencies and start the app:

   ```bash
   python -m pip install -r requirements.txt
   python app.py
   ```

Keep `.env` private and do not upload it to a public repository. Never store or display users' original passwords: the admin dashboard intentionally cannot read them because only one-way password hashes are stored. OTPs are also stored as hashes. This is a demo implementation; before public deployment, add HTTPS, rate limiting, CSRF protection, audit logs, secure backups, and a production WSGI server.
