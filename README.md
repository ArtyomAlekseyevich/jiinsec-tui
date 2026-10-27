# jiinsec-tui

A terminal client for [jiin.party](https://jiin.party).

Global chat, direct messages, group chats, forums, announcements and the image-metadata
tool, all from the terminal. Pictures show inline — real pixels in Kitty, block
characters elsewhere. Colours follow your Hyprland/Saber theme.

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
- `Ctrl+B` toggles the members list
- `F7` toggles inline pictures, `F8` cycles picture quality, `F9` toggles transparency
- In chat: type to send, `/img <path>` or drag a file in to send a picture, `i` on a
  message opens a picture full size

Voice calls, the globe and the music player need a browser.

## Image Data

The Image Data tab reads a photo's metadata (GPS, camera serials, timestamps, names)
and can save a stripped copy. It runs entirely on your machine.
