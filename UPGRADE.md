# UPGRADE.md — staying in sync with upstream

This fork adds a **per-session auto-attach location** feature on top of
[`nesquena/hermes-webui`](https://github.com/nesquena/hermes-webui) (upstream).

## Git remotes (already configured)

| remote | URL | role |
|---|---|---|
| `origin` | `https://github.com/fakoli/hermes-webui.git` | your fork — feature home |
| `upstream` | `https://github.com/nesquena/hermes-webui.git` | the original — source of truth |

Local branch: `master`. Your feature commits sit on top of upstream's history.

## How to upgrade (sync with upstream)

> **TL;DR:** `scripts/sync-upstream.sh` (dry-run) then `--rebase` when behind.

### After bootstrapping a fresh clone

```bash
git clone https://github.com/fakoli/hermes-webui.git ~/hermes-webui
cd ~/hermes-webui
git remote add upstream https://github.com/nesquena/hermes-webui.git
```

### Routine sync (run periodically, e.g. weekly)

```bash
cd ~/hermes-webui
scripts/sync-upstream.sh            # 1. dry-run: reports how far behind + conflict surface
scripts/sync-upstream.sh --rebase   # 2. actually rebase local commits on top of upstream
git push origin master              # 3. push the result to your fork
```

The script:
- **Refuses** to run with uncommitted changes (commit/stash first).
- **Never force-pushes.**
- On conflict, git stops and lists the files; resolve manually, then
  `git rebase --continue`.

### After the rebase, restart the WebUI server

The WebUI runs as a launchd agent `ai.hermes.webui` (Python server on
`127.0.0.1:8787`, proxied via `tailscale serve` on `:8443`). Static files
(`static/`) are picked up on browser refresh, but **Python changes
(`api/*.py`) require a server restart**:

```bash
launchctl bootout gui/$(id -u)/ai.hermes.webui 2>/dev/null
sleep 2
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.hermes.webui.plist
```

⚠️ `launchctl bootstrap` is **blocked from inside the Hermes gateway** (safety
guard) — run it from your own terminal, not via the agent.

Verify: `curl -sk https://fakoli-mini.tail4378d.ts.net:8443/health` → `ok`,
and `POST /api/location` with a real session returns `{"ok": true}`.

## Feature summary (what this fork adds)

Per-session auto-attach location, transparent like a website:

| File | What |
|---|---|
| `api/models.py` | `Session.location` field (persisted) |
| `api/routes.py` | `GET/POST /api/location` handlers + route registration |
| `api/streaming.py` | inject stored location into agent **ephemeral system prompt** every turn |
| `static/index.html` | location pin button + **Settings → Conversation → "Ask for my location on new conversations"** toggle |
| `static/boot.js` | auto-attach logic (one-time browser ask, POST, status chip) |
| `static/messages.js` | fire auto-ask from `send()` (first message in session) |
| `static/sessions.js`, `static/ui.js` | refresh status chip on session load |
| `static/style.css` | `.location-auto-chip` styling |
| `static/i18n.js` | English strings for toggle + chip |
| `scripts/sync-upstream.sh` | this sync helper |

### Behavior

- First message in a new conversation → browser asks location **once** (native
  prompt) → coordinates POSTed to `/api/location`, stored per-session.
- Agent sees `Location: <lat>, <lon> (±<acc>m)` in its ephemeral system
  context every turn — **not** in visible history.
- Status chip near composer: `📍 <label>` or `📍 Location on` (no raw
  coordinates). Click chip to clear.
- Toggle off in Settings → no prompts; manual pin button still works.

## Conflict-resolution notes (when upstream touches our files)

- If upstream edits `api/routes.py` / `api/streaming.py` / `api/models.py`
  around our seams (`_handle_chat_location_*`, `_webui_surface_context_prompt`,
  `surface_context`): resolve keeping both — our feature is additive and
  isolated.
- `static/boot.js`, `static/index.html`, `static/i18n.js` are high-churn
  upstream; our additions are small and anchored to nearby markers, so
  conflicts are usually trivial (`git rebase` shows them clearly).

## Testing after upgrade

```bash
# syntax
python3 -m py_compile api/models.py api/routes.py api/streaming.py server.py
node --check static/boot.js static/messages.js static/sessions.js static/ui.js static/i18n.js
# API round-trip (needs auth cookie; see below)
```

Auth for curl checks (password is in `~/.hermes/.env` as `HERMES_WEBUI_PASSWORD`
or `~/hermes-webui/.webui-password.txt`):

```bash
PW=$(cat ~/hermes-webui/.webui-password.txt)
curl -sk -c /tmp/wc -X POST https://fakoli-mini.tail4378d.ts.net:8443/api/auth/login \
  -H 'Content-Type: application/json' -d "{\"password\":\"$PW\"}"
# then use -b /tmp/wc on /api/location checks
```
