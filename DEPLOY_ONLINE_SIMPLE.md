# Put WayWise online (simple steps)

## Before uploading
- Keep `.env` and `waywise.db` private. They are excluded by `.gitignore`.
- Do not commit passwords, SMTP credentials, or real user data.

## Deploy with Render
1. Create a private GitHub repository and upload the project files (not `.env` or `waywise.db`).
2. Create a Render account and choose **New → Blueprint**. Connect the GitHub repository containing `render.yaml`.
3. Render reads `render.yaml` and creates the web service and persistent disk. The persistent disk uses a paid Render plan.
4. In Render's environment settings, set `WAYWISE_ADMIN_PASSWORD` to a strong unique password (you can use `ADMIN1234` for a quick demo, but change it before sharing publicly), `WAYWISE_ADMIN_EMAIL`, and SMTP settings. For Gmail, use a Google App Password.
5. Deploy. Render gives the service a public HTTPS URL, similar to `https://waywise-safe-route.onrender.com`. Your exact URL appears in the Render dashboard.
6. Open the URL and test registration, email OTP, password reset, user login, and `/admin`.

## Important
- OTP email will not work until valid SMTP environment variables are configured.
- Admin initial password is set by `WAYWISE_ADMIN_PASSWORD` on first database initialization. If an admin already exists in the database, changing that variable does not automatically reset its password.
- Never share the admin password or commit `.env` / database files to GitHub.
- The persistent disk requires a paid Render plan. Do not deploy real user accounts on temporary storage.
