# FjordCasino

Et dansk hyggekasino til FjordHub med virtuelle mønter. Ingen indbetaling, køb eller udbetaling af penge.

- Andedammen, Stjernestøv og Frugtfesten: tre spilleautomater med tre vandrette gevinstlinjer.
- Roulette Royale og Anderoulette: europæisk roulette med ét nul.
- Blackjack Club: seks kortspil, dealer står på alle 17, blackjack 3:2, mulighed for fordobling. Ingen split eller forsikring.
- Texas Hold’em mod 2–6 venner, også på tværs af installationer. Indskud og gevinster bruger den almindelige saldo.
- 10.000 startmønter og 500 for hver 15 minutters tilstedeværelse med kasinoet åbent, også i en baggrundsfane eller en minimeret browser. Delvise kvarterer gemmes; offline tid giver ingen optjening. Flere faner tæller ikke dobbelt.
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

Ved domæneadgang i FjordHub-tilstand konfigurerer `wsgi.py` også Waitress til at acceptere ét `X-Forwarded-Proto`-led. Dermed bevares HTTPS-oplysningen frem til Flask, så login og optjening ikke afvises som forespørgsler fra en anden origin. Andre proxyheaders forbliver fjernet af Waitress. Ændringer i `wsgi.py` kræver et nyt container-build; en genindlæsning af browseren er ikke tilstrækkelig.

`DATA_DIR` indeholder `casino.sqlite3`, eventuelle WAL/SHM-filer og `session.key`. Alle saldi og igangværende hænder overlever genstart. Sessionsnøglen skal bevares. Ved filbackup: stop appen, kopiér hele datamappen, start appen igen. Ingen produktionsdata eller nøgler må lægges i Git.

```sh
docker compose stop fjordcasino
# Tag en kopi af hele DATA_DIR her.
docker compose start fjordcasino
git pull --ff-only
docker compose up -d --build
```

FjordHub-installationer opdateres gennem FjordHub. Skemaversion 3 opretter tabeller uden at slette data. Ved rollback bruges en tidligere kodeversion sammen med dens kompatible backup; genindlæsning af en backup mister runder spillet siden backup. `docker compose down` bevarer bind-mappens data.

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

## Engangsnulstilling i 1.1.0

Ved første login efter denne opdatering nulstilles hver spillers saldo til 10.000, og gammel spilhistorik, runde-id’er og igangværende blackjackhånd ryddes. Konto og adgangskode bevares. En permanent markering pr. spiller forhindrer yderligere nulstillinger ved login, genstart eller senere opdateringer. Gamle sessioner skal logge ind igen. Databasen røres først for den enkelte spiller ved login. Tag backup før opdateringen, hvis den gamle saldo/historik skal bevares.

Tilstedeværelse registreres med et signal fra hver åben fane hvert 20. sekund, også når fanen er skjult. Serveren accepterer op til 90 sekunder mellem signalerne, da baggrundsfaners timere kan blive begrænset til én gang i minuttet. Ved lukning eller navigation væk pauses fanen. Udebliver signaler i mere end 90 sekunder, medregnes hullet ikke. En fane, som browseren suspenderer helt, eller en computer i dvale, kan derfor ikke fortsætte optjeningen. Det er browserbaseret tilstedeværelse og kan ikke bevise, at et menneske sidder ved skærmen.


## Poker med venner

1. Begge installationer opdateres til mindst 1.2.0. Log ind og vælg **Poker**.
2. Værten vælger **Opret bord**. 1.000 mønter reserveres fra værtens saldo.
3. Kontrollér adressen over vennekoden. Brug værtens offentlige HTTPS-domæne, når en ven er udenfor lokalnettet. På samme netværk bruges for eksempel `http://192.168.1.110:8070`.
4. Del hele `FC1.…`-vennekoden. Vennen indsætter den i sin egen installation og vælger **Forbind**. Hans 1.000 mønter reserveres på hans installation.
5. Værten starter hånden. Der er 2–6 pladser, blinds 10/20, check, kald, fold, hæv og all-in. Bedste fem af syv kort vinder; sidepuljer og delte puljer understøttes. Manglende handling i 60 sekunder giver automatisk fold, når bordet opdateres.
6. Vælg **Forlad bordet** for at føre dine resterende jetoner tilbage til din egen saldo. Under en hånd foldes dine kort, og afregning afventer afslutningen. Hvis værten forlader bordet, overtager næste spiller retten til at starte hænder.

Din makkers installation behøver ingen offentlig adresse, når din installation er den tilgængelige vært. Hans server forbinder ud til din via `/api/poker/peer`. Ingen indgående forbindelse til hans installation er nødvendig. Værtens adresse skal kunne nås fra gæstecontaineren; en privat LAN-adresse virker kun på samme net eller gennem en eksisterende VPN. DNS/HTTPS og eventuelle adgangsregler hos din reverse proxy skal tillade denne API-adgang. Der kræves ikke FjordHub-login på peer-endpointet; adgang styres af bordets hemmelige vennekode og separate spillertokens.

Indskud, spilleadgang, bordets tilstand og afregningskvitteringer gemmes i SQLite. Et mistet svar ved tilslutning eller tilbageførsel kan efterprøves uden nyt indskud eller dobbelt udbetaling. **Hent eksisterende forbindelse** genoptager et afventende indskud. Et fuldt bord returnerer indskuddet med en gemt kvittering. Ved varig utilgængelighed af værten forbliver indskuddet reserveret, indtil bordet kan kontaktes igen; det refunderes ikke uden en afregningskvittering.

Spil kun med en betroet vært. Værtsinstallationen har serverens kort og beregner resultater; dette er et vennebord med virtuelle mønter, ikke et tillidsløst eller certificeret pokernetværk. Peer-adresser med loopback, link-local, indlejrede loginoplysninger eller redirects accepteres ikke. Private LAN-adresser er med vilje tilladt.

Pokerprøven `python tests/browser_poker.py` starter to uafhængige installationer på maskinens LAN-adresse, spiller en hel hånd i to Chromium-kontekster og verificerer begge saldi. Prøvedata fjernes bagefter. Liveforbindelsen mellem jeres to konkrete installationer er endnu ikke efterprøvet.
