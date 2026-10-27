# jiinsec-tui

A terminal client for [jiin.party](https://jiin.party).

## Running

Needs `python3`. The launcher sets up a virtualenv on first run.

```sh
./jiinsec
```

Log in with your existing jiin.party account (sign-up and password reset are on the
website). Your session is saved to `~/.config/jiinsec-tui/`, so you only log in once.

Options:

- `./jiinsec --offline` — run against a local mock server to try things out without
  touching the real site.
- `./jiinsec --dev` — reload automatically while editing the code.

## Keys

Press `F1` in the app for the full list. The basics:

- `F2`–`F6` switch between Chat, Messages, Forums, News and Image Data
- `Ctrl+B` toggles the members list, `Ctrl+P` opens plugins
- `F7` toggles inline pictures, `F8` cycles picture quality, `F9` toggles transparency
- In chat: type to send, `/img <path>` or drag a file in to send a picture, `i` on a
  message opens a picture full size

## Plugins

`Ctrl+P` lists plugins you can turn on or off; the choice is saved. Drop a module in
`jiin/plugins/` to add your own.

Included:

- **message-logger** — keeps deleted messages visible (dimmed red) instead of removing
  them, and appends them to `~/.config/jiinsec-tui/deleted-messages.jsonl`.

Voice calls, the globe and the music player are not yet implemented
