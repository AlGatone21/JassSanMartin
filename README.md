# ASS Jass · Associazione Sportiva Soazza

A Flask web app for the club's Jass table: Italian and German, solo games against bots, private multiplayer tables, physical score sheets, and physical or digital tournaments. The supplied ASS anniversary logo is included; a smaller web copy lives in `static/ass.png`.

## Run on your computer

Install Python 3.13 or newer. From this folder in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m flask --app app run
```

Open **http://127.0.0.1:5000**. You can also run `powershell -ExecutionPolicy Bypass -File .\start.ps1` from this folder. Stop the server with Ctrl+C.

macOS/Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m flask --app app run
```

No cloud account, JavaScript build step, or external API key is needed. After installing the Python packages, bot games, score sheets and tournaments work without internet while the local server runs. Data is saved in `instance/` by default. Keep this directory to keep your local data; it is excluded from Git.

## Play and keep score

- **Gioca / Spielen:** start a solo table or create a private room. Share the room link. Participants can choose open seats; opposite seats are partners. The host can fill empty seats with bots and start. A browser that already occupies a seat resumes that seat when reopening the link.
- Bot cards appear one at a time with two seconds to follow each play. Completed tricks stay on the table for two seconds, and player names identify cards both on the table and in the previous trick. Reduced-motion preferences keep the reading time while removing card travel.
- **Settings:** choose Schieber to 1,000, Schieber to 2,500 with multipliers, a 12-hand tournament game, or custom settings. Toggle Weis, Stöck and the Match bonus. The smart bot uses card strength, public play and partnership tactics; the easy bot chooses legal cards randomly.
- **Segnapunti / Zähltafel:** create a physical match, enter one team's card points and the complementary score out of 157, add bonuses and a multiplier, and save each hand. Undo the latest hand if needed and export CSV.
- **Tornei / Turniere:** create a round robin or knockout competition, enter team names one per line, and share the results page. Physical results are entered by the organizer. Digital fixtures create linked multiplayer tables; finishing a digital game records its result in the tournament. Knockout events show connected brackets with round columns, byes, scores, advancing winners and the tournament champion. The bracket scrolls on smaller screens and keeps your position when scores update.
- **IT / DE:** change the interface language. The browser remembers your preference.

Use a different browser profile or a private window to try a second player on the same computer. Sessions identify players and organizers; clearing cookies or changing browser loses that identity. Shared links allow viewing and joining, while only the original organizer can edit score sheets and tournament results. Keep that browser session for the event.

For other devices on your home network, run:

```powershell
.\.venv\Scripts\python.exe -m flask --app app run --host 0.0.0.0
```

Open `http://YOUR-COMPUTER-LAN-IP:5000` on the other devices. Windows may ask you to allow Python on your private network. The computer must stay on. A localhost link works only on the computer running Flask; for internet play use Render as described below.

## Rules and scope

Digital play implements **four-player partnership Schieber**, including four suit contracts, Obenabe, Undenufe, Schieben, legal-card enforcement, trick scoring, last-trick points, optional automatic Weis and Stöck, optional Match bonus, multipliers and successive hands. A standard deal contains 36 cards and 157 trick points.

This app uses **automatic declarations** and settles the target **at the end of a hand**. This differs from championship games that can end during a hand with Stöck–Wys–Stich priority. See [the rule notes](docs/RULES.md) for details. Other distinct Jass games such as Coiffeur and Differenzler are not digital game modes. Their results can still be recorded through physical tournament result entry.

## Put it on GitHub and Render

Follow [the deployment guide](docs/DEPLOYMENT.md). The included `render.yaml` provisions a Flask service and PostgreSQL database. **That Blueprint uses paid Render resources**; review the plans before confirming creation. A manually configured free service is also described for evaluation.

Production command:

```bash
gunicorn app:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT --timeout 60
```

Use **one worker and one service instance**: game and bracket updates are serialized inside the application process. Room state is persisted in SQL rather than held only in memory. More workers/instances would require cross-process locking to preserve this guarantee.

## Tests and project layout

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

GitHub Actions runs the tests on pushes and pull requests. Run `python tools/browser_smoke.py` with a local Chrome or Edge installation for additional browser smoke checks and screenshots. The script uses a temporary database and browser profile.

Run `python tools/animation_smoke.py` for the timing and card-attribution regression checks.

Run `python tools/bracket_smoke.py` to check bracket connections, advancement, score entry and mobile scrolling.

| File | Purpose |
| --- | --- |
| `app.py` | Flask routes, sessions, access checks and room actions |
| `jass/engine.py` | Rules, card legality, scoring and bot strategy |
| `jass/storage.py` | SQLite/PostgreSQL storage |
| `jass/competitions.py` | Score sheets, tournament fixtures and standings |
| `templates/index.html` | Application shell |
| `static/js/app.js` | Browser UI, translations and multiplayer refresh |
| `static/css/app.css` | Responsive ASS club styling and cards |
| `render.yaml` | Render service and database configuration |

The original logo remains in `ass.png`. Club artwork remains the property of its respective owner.
