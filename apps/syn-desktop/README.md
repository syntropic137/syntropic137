# syn-desktop

The Syntropic137 desktop app (Skyline spec, Platforms: Desktop app, phase 5). It is a Tauri 2 window that loads the `apps/syn-ui` build and adds what a browser tab can't do:

| Feature | How |
|---|---|
| Native menu bar | App/File, Edit, View, Go (Cmd/Ctrl+1 to 8 for the eight sections), Window |
| Global Cmd/Ctrl+K | Emits `syn://command-palette`, then shows and focuses the window. Saved as `globalShortcut`, where `""` turns it off |
| Tray Live dot | The page calls `set_live_state` with `live`, `connecting`, `offline` or `fixtures`, and the tray icon dot, tooltip and status row follow it |
| Deep links | `syn137://executions/<id>` goes to `/executions/<id>`, and `syn137://executions` goes to `/executions`. Cold-start links wait until the page calls `desktop_ready` |
| API base URL | Saved with tauri-plugin-store in `settings.json` under `apiBaseUrl`. It must be an absolute http(s) URL; a trailing slash is removed |

Closing the window hides it. The app keeps running in the tray. Quit from the menu, the tray or Cmd+Q.

## Layout

```
bridge/index.ts      what apps/syn-ui imports: no-ops in a browser, no dependencies
src-tauri/           the Rust shell (lib.rs: commands + events, menu.rs, tray.rs, deeplink.rs, settings.rs)
scripts/make-icons.py  placeholder icons; swap in real art with `pnpm tauri icon <1024px.png>`
```

## Run

You need Rust 1.77.2 or newer and the Tauri system dependencies. On Debian or Ubuntu that means `libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev libssl-dev libxdo-dev`.

```sh
cd apps/syn-desktop/src-tauri
cargo tauri dev     # or: pnpm --dir apps/syn-desktop dev (needs @tauri-apps/cli installed)
cargo test          # deep-link parsing, URL validation, tray dot
node --experimental-strip-types --test ../bridge/index.test.ts
```

`tauri dev` runs `pnpm --filter syn-ui dev` and loads `http://localhost:5174`, so `/api/v1` goes through the vite proxy. `tauri build` runs `pnpm --filter syn-ui build` and bundles `apps/syn-ui/dist`.

`tauri::generate_context!` reads `apps/syn-ui/dist` at compile time. Build syn-ui once before running `cargo check` on a fresh checkout.

## Wiring the web app

`apps/syn-ui/src/main.ts` checks for `window.__TAURI__` and only then lazy-imports `apps/syn-ui/src/lib/desktop.svelte.ts`, which imports `bridge/index.ts` by relative path (no workspace dependency, no lockfile change) and calls `startDesktop` before the app mounts. The plain browser build ships only that check; the bridge is a separate chunk it never loads. The tray dot follows `live.state` through `setLiveState`. Settings is not wired yet because syn-ui has no Settings route. The gateway image copies `bridge/` into its Skyline build stage for the same reason.

When no URL is saved, the packaged app uses the selfhost gateway, `http://localhost:8137/api/v1`, the same address the CLI uses. The API must then allow the app's origin through CORS: `tauri://localhost` on macOS and Linux, `http://tauri.localhost` on Windows. `apps/syn-api` currently allows only `localhost:5173` and `localhost:3000`.
