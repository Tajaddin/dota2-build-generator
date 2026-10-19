# Safety: what this app touches, and why it stays within Valve's rules

Short version: the app only listens to what Dota 2 itself sends through **Game State Integration**
(GSI), calls **public web APIs**, and reads **static data**. It never touches the game process, never
sends input, and the only file it writes into the Dota folder is the GSI config.

## Everything the app touches

| What | How | Why |
|---|---|---|
| `<Dota 2>\game\dota\cfg\gamestate_integration\gamestate_integration_d2bg.cfg` | Written when you click **Install** on the Setup page; deleted when you click **Remove** | This file is how Valve's GSI is switched on. The game reads it and starts sending JSON to the address inside it. |
| `<Steam>\steamapps\libraryfolders.vdf` and the registry value `HKCU\Software\Valve\Steam\SteamPath` | Read only | To find which drive Dota is installed on. |
| `http://127.0.0.1:4242` | A local web server: Dota POSTs GSI JSON to `/gsi`; your browser loads the UI | Loopback only by default. LAN mode (for a phone) is opt-in and needs a token. |
| `https://api.opendota.com` | HTTPS requests, about 1 per second at most, cached on disk | Hero, item, meta, matchup and benchmark data, your public profile and matches, replay-parse requests. |
| `https://cdn.cloudflare.steamstatic.com` | Image downloads by your browser | Hero and item pictures from Valve's public CDN. |
| `%LOCALAPPDATA%\d2bg\` | Read and write | Settings, API cache, refreshed data, GSI recordings. |

## Things the app never does

- Read or write the memory of `dota2.exe`, inject code, or load anything into the game.
- Draw inside the game. The optional compact window is an ordinary separate window.
- Send keystrokes or mouse clicks, or automate anything in the game or Steam.
- Capture network packets, the screen, or the game's console log.
- Write any game file other than the GSI config above, or change Steam settings or launch options.
- Use DotaPlus, Overwolf or any other private backend.

`tests/d2bg/test_safety.py` enforces this in CI. It fails the build if the package imports
process, input, capture or Windows-API libraries (`ctypes`, `pymem`, `pynput`, `pyautogui`,
`keyboard`, `mouse`, `scapy`, `win32api`, `mss`, ...), mentions calls such as `ReadProcessMemory`,
`OpenProcess` or `SendInput`, or writes into the Dota folder anywhere but the GSI installer.

## Why this is within the rules

1. **GSI is Valve's own interface.** Dota 2 ships with it. You enable it by placing a config file in
   the `gamestate_integration` folder, and the game decides what to send. While you play, it sends
   only your own hero, items, abilities and the match clock. Data about all ten players is sent only
   when you spectate or cast. The app shows enemy items only in that case.
2. **Valve's 2023 ban wave targeted reading hidden client data.** In February 2023 Valve banned over
   40,000 accounts for third-party software that read information from the game client that players
   cannot see ("Cheaters Will Never Be Welcome in Dota",
   <https://www.dota2.com/newsentry/3677788723152833273>). This app reads nothing from the client; it
   receives only what GSI sends.
3. **Public APIs.** OpenDota is a public, documented API built on public match data. The client stays
   under its published limits (read from its response headers).
4. **No automation.** Every action in the game is yours. Timers and suggestions are information.

## If no GSI data arrives

Some Dota builds only enable GSI when the game is started with the `-gamestateintegration` launch
option. The app will not edit your launch options. If the Setup page never sees a packet, add it
yourself: Steam → Library → Dota 2 → Properties → General → Launch options.

## The v1 desktop app

The older desktop app in this repo (`python main.py`) uses `pynput` to listen for one global hotkey
that toggles its overlay. It listens only; it never sends input. The new app (`d2bg`) has no global
keyboard hook at all; its shortcuts work only inside the browser tab.

## Limits of this statement

This is a reading of Valve's public statements and the GSI design, not a guarantee from Valve. Valve
can change its rules. Don't run this alongside software that does any of the things listed under
"never", because a ban would apply to the account, not to one program.
