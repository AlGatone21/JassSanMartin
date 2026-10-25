# GitHub and Render deployment

## 1. Check locally

Run the application using the commands in [README.md](../README.md), create a bot game and save a physical score sheet. Install the development requirements and run `python -m pytest -q` using your virtual environment before publishing changes.

## 2. Push this folder to GitHub

Create an empty repository in your GitHub account. Do not initialize it with a README because this folder already contains one. In PowerShell, from this folder, replace `YOUR-USERNAME` and the repository name below:

```powershell
git init
git add .
git commit -m "Build ASS Jass web app"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/ass-jass.git
git push -u origin main
```

Git may ask you to configure your name/email or sign in to GitHub. The `.gitignore` keeps your virtual environment, local database, secret key and `.env` out of the repository. Review `git status` before committing. The logo is intentionally included.

## 3. Deploy with the included Blueprint

1. Sign in to Render and connect your GitHub account.
2. Choose **New → Blueprint**, then select this repository and branch `main`.
3. Render reads `render.yaml`. Review the proposed web service and PostgreSQL database, region and billing before confirming. The file requests a **Starter web service and Basic PostgreSQL database**, which are paid resources.
4. Confirm creation. The Blueprint supplies a generated `SECRET_KEY`, the database connection and secure cookies. Wait for the service to become live, then open its `https://…onrender.com` URL.
5. Create a multiplayer room and open its shared link in another browser to check joining. Create a score sheet, restart the service and confirm it is still visible using the same browser.

The resource definitions follow [Render's Blueprint specification](https://render.com/docs/blueprint-spec). The root `.python-version` selects the latest Python 3.13 patch supported by Render, using [Render's Python version configuration](https://render.com/docs/python-version).

## Alternative: configure the service manually

Create a PostgreSQL database and a Python Web Service connected to your GitHub repository. Place both resources in the same region. Use the database's **Internal Database URL** as the web service's `DATABASE_URL`, following [Render's PostgreSQL connection guide](https://render.com/docs/postgresql-creating-connecting).

Set the web service values:

| Setting | Value |
| --- | --- |
| Runtime | Python 3 |
| Branch | `main` |
| Build command | `pip install -r requirements.txt` |
| Start command | `gunicorn app:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT --timeout 60` |
| Health check path | `/health` |
| `DATABASE_URL` | Your database's Internal Database URL |
| `SECRET_KEY` | A long, randomly generated secret, kept stable across deploys |
| `SESSION_COOKIE_SECURE` | `true` |

Generate the secret on your computer:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Paste it into Render's environment settings, not into Git. The Flask deployment pattern and Gunicorn entry point follow [Render's Flask guide](https://render.com/docs/deploy-flask).

A free web service can be used for evaluation. Free services sleep when idle and can take time to wake up. Check the current database plan's retention and expiration terms before storing tournament results. See [Render's free service documentation](https://render.com/docs/free).

## Persistence and updates

**Use PostgreSQL on Render for data you want to keep.** The app falls back to a local SQLite file without `DATABASE_URL`; Render's default filesystem is ephemeral, so that file would be lost across deployments. A paid persistent disk is another possible setup, but is not used by this Blueprint. See [Render's filesystem and deploy behavior](https://render.com/docs/deploys).

Keep the same `SECRET_KEY` after deploying: changing it invalidates browser sessions and loses guest organizer/seat access. Local data is not automatically uploaded to the hosted database. Start hosted events on the hosted site.

Push future changes to the connected branch:

```powershell
git add .
git commit -m "Describe your change"
git push
```

With automatic deploys enabled, Render deploys the new commit. Keep the configured **one Gunicorn worker and one service instance** because updates are synchronized with an application-process lock. Before larger public events, arrange database backups and test the expected number of concurrent tables on your chosen service plan.

## Troubleshooting

- **Application error:** read the web service's Render logs. Check dependency installation, the database URL and the start command.
- **Can't join a local room from another phone:** use the server computer's LAN IP, bind to `0.0.0.0` and allow your private network through the firewall. `127.0.0.1` points to the device opening the link.
- **Local secure-cookie problem:** leave `SESSION_COOKIE_SECURE=false` locally; use `true` on Render HTTPS.
- **Lost organizer controls:** reopen the same browser profile. Guest identity is stored in its session cookie and is not an account with password recovery.
- **Render data disappears:** configure `DATABASE_URL`. A local SQLite database on an ephemeral filesystem is temporary.
