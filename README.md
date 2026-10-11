# FjordCasino

Et dansk hyggekasino til FjordHub med virtuelle mønter. Ingen indbetaling, køb eller udbetaling af penge.

- Andedammen, Stjernestøv og Frugtfesten: tre spilleautomater med tre vandrette gevinstlinjer.
- Roulette Royale og Anderoulette: europæisk roulette med ét nul.
- Blackjack Club: seks kortspil, dealer står på alle 17, blackjack 3:2, mulighed for fordobling. Ingen split eller forsikring.
- 5.000 startmønter og automatisk 1.000 mønter ved dagens første besøg. Dagsskift følger `TZ` (standard `Europe/Copenhagen`).
- Personlig saldo, seneste 50 bevægelser og gemt blackjackhånd. Spil afgøres og afregnes på serveren, i én databasetransaktion. Runde-id beskytter mod dobbelt afregning.

## FjordHub

Opdater FjordHubs appkatalog og installér **FjordCasino**. Standardport er **8070**. Tildel brugerne adgang i FjordHub. Appen bruger `docker-compose.fjordhub.yml`, og FjordHub leverer `FJORDHUB_URL` og `FJORDHUB_API_KEY`. Login og brugeradgang styres centralt; appen ændrer ikke FjordHub-konti.

## Selvstændig installation

```sh
cp .env.example .env
docker compose up -d --build
docker compose logs --tail=100 fjordcasino
```

Åbn `http://localhost:8070`. Standalone bruger lokal registrering; brug FjordHub-udgaven, hvis kun inviterede brugere skal kunne logge ind. HTTP virker på lokalnettet. Ved offentlig adgang skal en betroet reverse proxy levere HTTPS. I FjordHub-tilstand stoles på ét `X-Forwarded-Proto`-led; backendporten bør derfor kun være tilgængelig fra den betroede proxy/lokalnettet. Forwarded host og client-IP stoles ikke på. Sessionscookies er HttpOnly/SameSite=Lax og Secure ved HTTPS.

Appcontaineren kører som UID 10001 uden Linux capabilities. En separat init-container indstiller ejerskab og adgang på selve datamappen. Brug en dedikeret lokal mappe (SQLite bør ikke placeres på NFS/SMB).

## Data, opdatering og backup

`DATA_DIR` indeholder `casino.sqlite3`, eventuelle WAL/SHM-filer og `session.key`. Alle saldi og igangværende hænder overlever genstart. Sessionsnøglen skal bevares. Ved filbackup: stop appen, kopiér hele datamappen, start appen igen. Ingen produktionsdata eller nøgler må lægges i Git.

```sh
docker compose stop fjordcasino
# Tag en kopi af hele DATA_DIR her.
docker compose start fjordcasino
git pull --ff-only
docker compose up -d --build
```

FjordHub-installationer opdateres gennem FjordHub. Skemaversion 1 opretter tabeller uden at slette data. Ved rollback bruges en tidligere kodeversion sammen med dens kompatible backup; genindlæsning af en backup mister runder spillet siden backup. `docker compose down` bevarer bind-mappens data.

## Lokal udvikling og test

Python 3.13 anbefales. Installer `requirements.txt` og `requirements-dev.txt`. `tzdata` leverer tidszoner også på Windows.

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q
python -m playwright install chromium
python tests/browser_smoke.py
```

Start lokalt med `AUTH_MODE=local python app.py` (PowerShell: `$env:AUTH_MODE='local'; python app.py`). Udviklingsserveren binder kun loopback på port 8070. Docker bruger Waitress på port 8080. `/api/health` kontrollerer databaseadgang.

Browserprøverne starter deres egen server og bruger midlertidige data og syntetiske spillere. Ingen tests kontakter en rigtig FjordHub eller spiller med rigtige konti. GitHub Actions kører tests samt container-build og sundhedstjek.
