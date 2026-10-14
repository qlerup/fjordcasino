# FjordCasino

A casual FjordHub casino with virtual coins, without real-money deposits, purchases or withdrawals. The interface currently uses Danish labels.

## Games and rewards

- Andedammen, Stjernestøv and Frugtfesten: slots with three horizontal winning lines.
- Roulette Royale and Anderoulette: European single-zero roulette.
- Blackjack Club: six decks, dealer stands on all 17s, blackjack pays 3:2, doubling; no split or insurance.
- Texas Hold'em with 2–6 friends, including across installations, using ordinary wallets for buy-ins/winnings.
- 50,000 starting coins and 500 per 15 minutes with the casino open, including background tabs/minimized browsers. Partial periods persist, offline time earns nothing and tabs do not multiply rewards.
- Personal wallet, last 50 movements and saved blackjack hand. Server-side transactional settlement and round IDs prevent duplicate settlement.

## Install through FjordHub

Install **FjordCasino**, default port **8070**, and assign access in Hub. `docker-compose.fjordhub.yml` receives Hub's integration URL/key. Shared login, SSO and first-login email/password setup use the central account.

Hub administrators can require an email confirmation/update. Existing logins receive a mandatory form when opening or returning to the app. Saving a valid, unique address clears the requirement across updated apps without replacing the account/wallet. Update both Hub and Casino. Current membership is rechecked during sessions.

## Standalone deployment

```sh
cp .env.example .env
docker compose up -d --build
docker compose logs --tail=100 fjordcasino
```

Open `http://localhost:8070`. Standalone permits local registration; use Hub-managed access for an invited-user deployment. HTTP works on trusted LANs; public access requires HTTPS.

In managed mode, Flask and Waitress accept one `X-Forwarded-Proto` hop, preserving HTTPS login/reward origins. Other forwarded host/client-IP headers remain untrusted. Restrict the backend to a trusted proxy/LAN. Cookies are HttpOnly/SameSite=Lax and Secure under HTTPS. Proxy-handling changes require rebuilding, not just refreshing the browser.

The container runs as UID 10001 without Linux capabilities. An init container configures the dedicated data directory. Keep SQLite on local disk, not NFS/SMB.

## Poker with friends

1. Update both installations to a compatible poker release (at least 1.2.0), log in and open Poker.
2. Create a table; the host reserves 1,000 wallet coins.
3. Check the address above the friend code. Use the host's reachable HTTPS origin for remote players or its LAN address on the same network.
4. Share the complete `FC1.…` code. A friend connects from their installation and reserves their own 1,000 coins locally.
5. Start a hand: 2–6 seats, 10/20 blinds, check/call/fold/raise/all-in, best-five-of-seven evaluation, side pots and split pots. After 60 seconds without action, refresh applies an automatic fold.
6. Leave to return remaining chips to your wallet. Leaving during a hand folds and waits for settlement. The next player can start hands if the host player leaves.

Both installations show action feedback and the winning hand. Made combinations are highlighted without unrelated kickers; celebrations remain until the next hand. Refunded uncalled bets are not winnings. Withdrawing players stay out of subsequent hands.

The guest connects outbound to the host's `/api/poker/peer`, so it needs no public inbound address. LAN addresses require the same network/routed VPN. Proxy rules must permit peer requests. Authentication uses the secret friend code and player tokens, not Hub login.

Buy-ins, table state and settlement receipts persist. Lost join/withdraw responses can be retried without duplicate debit/payout; Retrieve existing connection resumes a pending buy-in. Full tables refund with a receipt. If the host remains unreachable, escrow stays reserved until settlement can be confirmed. Only use trusted hosts: the host owns cards/results; this is not a trustless or certified poker network. Loopback, link-local, embedded credentials and redirects are rejected, while private LAN destinations are supported.

## One-time wallet migration in 1.3.0

The first login after that upgrade sets each wallet to exactly 50,000, clears old round IDs/unfinished blackjack and resets partial reward time. Account, password and history remain, with the adjustment recorded. Poker tables/escrow remain. A per-player marker prevents repeated resets on later logins or updates. Old sessions sign in again. Back up first if the old state must remain recoverable.

Presence heartbeats run every 20 seconds, including hidden tabs. The server tolerates 90 seconds because browsers throttle timers. Closing/leaving pauses presence; longer gaps earn nothing. Suspended tabs or sleeping computers cannot earn indefinitely. Presence does not prove a person is watching the screen.

## Data, updates and backup

`DATA_DIR` holds `casino.sqlite3`, WAL/SHM files and `session.key`. Preserve the complete directory/key. Stop before file backup. Schema version 3 creates tables without erasing data. Rollback needs compatible code/backup and loses rounds since that backup. Ordinary `docker compose down` preserves the bind mount.

```sh
docker compose stop fjordcasino
# Back up the complete DATA_DIR.
docker compose start fjordcasino
git pull --ff-only
docker compose up -d --build
```

Managed deployments update through Hub. Never commit production data or secrets.

## Development and tests

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q
python -m playwright install chromium
python tests/browser_smoke.py
python tests/browser_poker.py
```

Python 3.13 is recommended; `tzdata` supports Windows. Local development: `AUTH_MODE=local python app.py`, or `$env:AUTH_MODE='local'; python app.py` in PowerShell, on loopback port 8070. Docker runs Waitress on 8080; `/api/health` checks database access.

Browser tests use temporary synthetic players. The poker test starts two LAN-address fixtures and verifies a complete hand/balances, rather than claiming every deployed server pair has been checked. Actions runs tests, builds and health checks. See [branding/README.md](branding/README.md) for artwork.
