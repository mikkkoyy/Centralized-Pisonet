# MKY PisoNet Station Client (PISO-003)

C#/.NET 10 station client for [MKY PisoNet Central](../README.md).
Runs on a station PC, enrolls once with the operator's enrollment
secret, then heartbeats to the server every 10 seconds and displays
the server-authoritative session countdown.

## Layout

| Project | Purpose |
| --- | --- |
| `PisoNet.Client.Core` | Configuration, DPAPI credential storage, typed station API client, heartbeat loop, command processing, session countdown. No WinForms dependencies. |
| `PisoNet.Client.WinForms` | Dark-themed station window: connection dot, station code, live countdown, session state, last-sync staleness marker, lock banner, settings dialog. |
| `PisoNet.Client.Cli` | Headless operator client: `enroll`, `run`, `reset`. |
| `PisoNet.Client.Core.Tests` | 71 xUnit tests for Core. |

## Build and test

```powershell
dotnet build client\PisoNet.Client.slnx
dotnet test  client\PisoNet.Client.slnx
```

Requires the .NET 10 SDK (Windows; WinForms).

## CLI usage

```powershell
# Enroll once (secret via argument or PISONET_ENROLLMENT_SECRET)
dotnet run --project client\PisoNet.Client.Cli -- enroll `
    --server http://127.0.0.1:8000 --station PISO-01 --display-name "Counter 1"

# Run the heartbeat loop (Ctrl+C to stop)
dotnet run --project client\PisoNet.Client.Cli -- run

# Clear local configuration and stored credential
dotnet run --project client\PisoNet.Client.Cli -- reset
```

## Security properties

- **Credential storage**: the station bearer token is stored with
  Windows DPAPI (CurrentUser scope) under
  `%LOCALAPPDATA%\MKY\Pisonet\station.credentials`. Only the
  enrolling Windows user can decrypt it. It is never stored in
  plaintext and never logged.
- **Configuration**: `config.json` holds only non-secret settings
  (server URL, station code, display name, intervals).
- **No time fabrication**: the countdown is interpolated locally
  from the last server value and resynchronized on every
  heartbeat. It never adds time and is frozen (marked stale)
  while disconnected.
- **Commands**: only `lock`/`unlock` are implemented; anything
  else is ignored and never executed. Expired commands are never
  applied. Delivery is idempotent (applied and acknowledged once
  per client run).
- **Failure handling**: a failed heartbeat never unlocks the
  station or extends paid time. 401 (revoked/rotated credential)
  halts the client with an actionable message instead of
  retrying forever. Transient failures back off exponentially
  (2s base, 30s cap, jitter) and report `ServerUnavailable`
  after three consecutive failures.
- **Secrets in errors**: server error details are surfaced without
  echoing submitted values (FastAPI validation `input` members are
  stripped because they can contain the enrollment secret).

## Protocol (v1)

`X-Api-Version: 1` on every request. Bearer token after enrollment.
See `app/api/v1/stations.py` in the server for the wire contract.
