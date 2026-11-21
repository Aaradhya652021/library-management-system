# Public hosting (Cloudflare quick tunnel)

The site is served by **Waitress** and exposed through a **Cloudflare quick
tunnel**. This makes it reachable from anywhere at a temporary
`https://<random>.trycloudflare.com` URL while this computer is running.

## Start

Double-click `start_public.bat`, or run:

```powershell
.venv\Scripts\python.exe scripts\run_public.py
```

The public URL is printed in the window and saved to `public_url.txt`.

## Stop

Press `Ctrl+C` in the window, or close it. The public URL stops working
immediately.

## Important

- The quick-tunnel URL is **temporary**: it changes every time the script runs.
- This computer must stay on and connected; the site is not hosted elsewhere.
- Only HTTP traffic is tunnelled. MySQL stays local and is not exposed.
- The demo login is `<demo member e-mail>` / `demo1234`.
- **Change the admin password before sharing the URL widely.** The current
  admin login is still the default `admin` / `admin@123`. Anyone with the URL
  can reach `/login`. To change it:

  ```powershell
  .venv\Scripts\python.exe scripts/set_admin_password.py
  ```

  It prompts, hides input, and updates the stored hash. Use `--list` to show
  admin accounts. The change takes effect immediately; no restart is needed.

## If the URL stops working

1. Check the `run_public.py` window is still open.
2. Check the computer is awake and online.
3. Restart `start_public.bat` and use the new URL from `public_url.txt`.

## Files

- `scripts/run_public.py` — Waitress server + tunnel launcher.
- `tools/cloudflared.exe` — Cloudflare tunnel client.
- `public_url.txt` — last generated public URL (gitignored).
