# Automatic Meeting Recording

## Starting keepmeet

Double-click the **keepmeet** icon on your Desktop or in the Start menu. A minimized "keepmeet" window appears in the taskbar and the app opens in your browser at http://localhost:6070. Closing that window stops keepmeet. Double-clicking again while it's running just opens the app.

- Create or recreate the icons: `.venv\Scripts\keepmeet shortcut`
- Same thing from a terminal: `.venv\Scripts\keepmeet app`
- The web UI is rebuilt automatically when frontend files change.
- If keepmeet is closed during a call, the audio recorded so far is processed on the next start. So are jobs that were still processing when it closed.

## Publishing to Confluence (one-time setup)

1. **Settings → Confluence → Publish folder:** paste the folder link (e.g. `https://yourcompany.atlassian.net/wiki/spaces/TEAM/folder/123456/Meeting+Notes`) and click **Save**.
2. Create an Atlassian API token at https://id.atlassian.com/manage-profile/security/api-tokens, enter your Atlassian email and the token, then click **Connect**. The token is stored encrypted (Windows DPAPI) in `data/confluence_auth.json` and only works for your Windows account.
3. On a meeting, the **Confluence** card shows a generated page title (meeting name and date). Edit it if you like, then click **Publish**. Publishing again with the same title updates the existing page instead of creating a duplicate.

Notes are always written in English, whatever language was spoken. People's names, technical terms and ticket IDs are kept as they are.

There are two independent ways to get meetings in automatically. Use either one, or both.

## Option A: Record from this PC (no setup)

Open **Settings → Record from this PC**, turn it on, and click **Save**. While the keepmeet server is running:

- When you join a Teams call (the new Teams app holding your microphone), recording starts. You get a Windows notification and a red **REC** badge in the web UI.
- It captures everything your PC plays (the other participants) plus your default microphone, and mixes them into one track.
- About 15 seconds after the call ends, it stops, saves the audio, and processes it like any other job. The title comes from the Teams meeting window (e.g. `Team Daily - 2026-09-26`), or `Teams call - <date time>` if the name can't be read.
- Calls shorter than the minimum duration (60s by default) are discarded.
- **Record now** / **Stop** start and stop a recording manually, for any audio (a manual recording doesn't stop on its own).
- If you stop the server during a recording, the audio is saved and processed on the next start.

Notes:
- Teams must play through the **Windows default output device**, and your voice is captured from the **Windows default microphone**. If Teams uses a different headset than Windows does, the recording will miss that side.
- Teams in the browser isn't detected. Use the desktop app or **Record now**.
- Participants don't see a Teams recording banner. Let your team know you're recording.

## Option B: Teams cloud recordings

Once set up, the flow is fully hands-off: the daily meeting records itself → when the recording is posted, keepmeet-ai (running on your PC) finds it, downloads it, transcribes, diarizes, matches speaker profiles, formats notes, and either publishes them to Confluence or waits for your review, depending on your settings. A Windows notification tells you when it's done.

### 1. Make the meeting record itself (organizer, one time)

Ask the organizer of the recurring daily to open the meeting in Teams → **Meeting options** → turn on **Record and transcribe automatically** → Save. It applies to the whole series.

The recording is stored in the organizer's OneDrive and shared with everyone invited. Teams also posts it in the meeting chat, which is where keepmeet picks it up.

### 2. Register an Entra app (one time, ~2 minutes)

1. Go to https://entra.microsoft.com → **Identity → Applications → App registrations → New registration**
2. Name: `keepmeet-ai`
3. Supported account types: **Accounts in this organizational directory only**
4. Redirect URI: leave empty
5. After creation, open **Authentication** → under **Advanced settings** set **Allow public client flows** to **Yes** → Save
6. Open **API permissions** → **Add a permission → Microsoft Graph → Delegated permissions** → add `Files.Read.All`, `User.Read` and `Chat.Read`

These are delegated, read-only permissions: the app acts as you and can only read files and chats you can already see. In most tenants no admin consent is needed. If your tenant blocks user consent, ask IT to consent to these three delegated permissions.

From the app's **Overview** page copy:
- **Application (client) ID** → `GRAPH_CLIENT_ID`
- **Directory (tenant) ID** → `GRAPH_TENANT_ID`

### 3. Configure keepmeet-ai

Add to `.env`:

```
GRAPH_CLIENT_ID=<application client id>
GRAPH_TENANT_ID=<directory tenant id>
```

### 4. Sign in (one time)

Start the server, open the web UI → **Settings** → **Sign in with Microsoft**, then enter the code shown at the Microsoft link. Or from the terminal:

```
keepmeet teams login
```

The token is cached in `data/graph_token_cache.json` and refreshed automatically. If you signed in before `Chat.Read` was added, Settings shows "No meeting chat access". Sign in again once to grant it.

### 5. Choose your options (Settings page)

| Setting | What it does |
|---|---|
| **Meeting chats** | Finds recordings posted in Teams meeting chats. Works for meetings organized by someone else (recommended). |
| **My OneDrive Recordings** | Finds recordings in your own OneDrive `Recordings` folder (meetings you recorded). |
| **Shared with me** | Fallback: scans recording files shared with you. Less reliable. |
| **Meeting name filter** | Only process meetings whose name contains this text (e.g. `Daily`). Empty = every meeting. |
| **Check every** | Polling interval in seconds. |
| **After processing** | **Manual review**: notes wait for you to click Publish. **Auto if all speakers matched**: publish only when every speaker matched a voice profile. **Auto-publish**: always publish. |
| **Windows notifications** | Toast when a recording is found, notes are ready or published, or something fails. Click it to open the job. |

Settings are stored in `data/settings.json`. The `teams:` block in `config.yaml` only provides the initial defaults.

### How cloud ingestion works

- The watcher runs only while the server is running. Anything recorded while it was off is picked up on the next start.
- The first time a source is enabled, it only notes what already exists. Recordings that appear **after** that are processed.
- Meeting chats: recordings are processed once Teams marks them finished. Files are downloaded through your Graph access to the shared recording.
- The same recording found by several sources is processed only once.
- Titles come from the Teams filename plus the date (e.g. `Team Daily - 2026-09-26`), so each day gets its own Confluence page.
- For a one-off meeting, paste the Teams recap or SharePoint link into **New Transcription → From Teams Link**.

## Troubleshooting

- Settings shows per-source errors. `GET /api/teams/status` returns the same information. `keepmeet teams status` shows the configuration.
- `Not signed in` → sign in again from Settings (the cache may have been deleted, or the refresh token expired after long inactivity).
- `No Chat.Read access` → sign in again to grant the new permission.
- Nothing ingested → check the meeting name filter, check that the recording is posted in the meeting chat, and use **Check now** in Settings.
- To re-ingest a recording that was already tracked, delete its entry from `data/teams_ingest.json` or paste its link into From Teams Link.
