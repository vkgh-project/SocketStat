# Upload this folder to PythonAnywhere EU

1. Upload the entire `dist` folder into your PythonAnywhere home directory,
   keeping its subfolders. It should be `/home/YOURUSERNAME/dist`.
2. Edit `config.env` on PythonAnywhere. Fill in your Tuya credentials, both socket
   IDs, and a dashboard password of at least 12 characters. Keep this file private.
3. In PythonAnywhere **Account → API token**, generate a token if you do not
   already have one. You do not need to copy the token into any file.
4. Open a PythonAnywhere **Bash console** and run:

   ```bash
   cd ~/dist
   bash deploy.sh
   ```

Open `https://YOURUSERNAME.eu.pythonanywhere.com` and log in with the dashboard
username and password from `config.env`.

The script installs dependencies and creates the ASGI website. This uses
PythonAnywhere's experimental ASGI hosting, not the standard WSGI Web setup.
If you already have a website using this domain, resolve that conflict before
running the deployment script; this script does not delete existing sites.

The app creates its database in `dist/data/socketstat.db`. Keep that folder when
updating the app. This package starts a new history; local credentials and your
existing database are not included. `start.sh` sets the database path automatically,
so you can leave `DB_PATH` in `config.env` unchanged.

After changing uploaded code or `config.env`, run:

```bash
~/dist/.venv/bin/pa website reload --domain YOURUSERNAME.eu.pythonanywhere.com
```

Free accounts restrict external API access. Your Tuya endpoint must be allowed;
paid accounts have unrestricted outbound access. Collection runs inside the web
process and pauses during restarts. Keep one worker to avoid duplicate polling.

Official hosting instructions:
https://help.pythonanywhere.com/pages/ASGICommandLine/

## Check Tuya access

From the uploaded folder, run:

```bash
.venv/bin/python check_tuya.py
```

This checks authentication and reads both socket statuses without changing the
database or controlling the sockets. Its output contains no credentials or tokens.
The dashboard also shows the latest polling error beside the last-check time.

If the console check succeeds but the website records `network_error`, the web
process may be missing the proxy environment setting. On a free PythonAnywhere
account, add this to `config.env` and reload the website:

```dotenv
HTTPS_PROXY=http://proxy.server:3128
```

HTTPX reads this setting automatically after the app loads `config.env`. Use
`http://` for the proxy address even though the Tuya endpoint uses HTTPS.
