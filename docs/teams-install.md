# Installing MOCHI-kiki in Teams Meetings

## Overview

Three things are required to use the bot in Teams meetings:

1. Register an app in Microsoft Entra (to get `APP_ID` / `APP_PASSWORD`)
2. Register in Azure Bot Service (to enable the Teams channel)
3. Create and upload a Teams app manifest

---

## Step 1 — Register an App in Microsoft Entra

1. [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID** → **App registrations** → **New registration**
2. Settings:
   - Name: `MOCHI-kiki`
   - Supported account types: **Accounts in any organizational directory (Multi-tenant)**
   - Redirect URI: leave blank
3. After registering, copy the **Application (client) ID** → set as `MICROSOFT_APP_ID` in `.env`
4. **Certificates & secrets** → **New client secret** → copy the value → set as `MICROSOFT_APP_PASSWORD` in `.env`

---

## Step 2 — Register in Azure Bot Service

1. Azure Portal → **Create a resource** → search "Azure Bot" → Create
2. Settings:
   - Bot handle: `mochi-kiki`
   - Subscription / Resource group: select existing
   - Microsoft App ID: **Use existing app** → enter the `APP_ID` from Step 1
3. After creation, go to **Configuration** → **Messaging endpoint** and enter:
   ```
   https://mochikiki-bot-dev--0000001.orangeglacier-d7a5339f.japaneast.azurecontainerapps.io/api/messages
   ```
4. **Channels** → Add **Microsoft Teams** → agree and save

---

## Step 3 — Create the Teams App Manifest

Create a `teams_app/` folder in the project root and add these 3 files.

### `teams_app/manifest.json`

Replace `MICROSOFT_APP_ID_HERE` with your actual App ID from Step 1:

```json
{
  "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.17/MicrosoftTeams.schema.json",
  "manifestVersion": "1.17",
  "version": "1.0.0",
  "id": "MICROSOFT_APP_ID_HERE",
  "packageName": "com.mochitec.mochikiki",
  "developer": {
    "name": "Mochitec",
    "websiteUrl": "https://mochitec.example.com",
    "privacyUrl": "https://mochitec.example.com/privacy",
    "termsOfUseUrl": "https://mochitec.example.com/terms"
  },
  "name": {
    "short": "MOCHI-kiki",
    "full": "MOCHI-kiki Meeting Assistant"
  },
  "description": {
    "short": "Auto-answers spec questions in meetings",
    "full": "Detects spec inquiries and ambiguous statements during Teams meetings and responds automatically using RAG."
  },
  "icons": {
    "color": "color.png",
    "outline": "outline.png"
  },
  "accentColor": "#0078D4",
  "bots": [
    {
      "botId": "MICROSOFT_APP_ID_HERE",
      "scopes": ["team", "groupChat"],
      "supportsFiles": false,
      "isNotificationOnly": false
    }
  ],
  "configurableTabs": [],
  "staticTabs": [],
  "permissions": ["identity", "messageTeamMembers"],
  "validDomains": [
    "mochikiki-bot-dev--0000001.orangeglacier-d7a5339f.japaneast.azurecontainerapps.io"
  ],
  "webApplicationInfo": {
    "id": "MICROSOFT_APP_ID_HERE",
    "resource": "https://graph.microsoft.com"
  },
  "authorization": {
    "permissions": {
      "resourceSpecific": [
        {
          "name": "OnlineMeeting.ReadBasic.Chat",
          "type": "Application"
        },
        {
          "name": "ChannelMessage.Read.Group",
          "type": "Application"
        }
      ]
    }
  }
}
```

### Icons

Prepare 2 PNG files and place them in `teams_app/`:

| File | Size | Description |
|------|------|-------------|
| `color.png` | 192×192 px | Full-color app icon |
| `outline.png` | 32×32 px | White icon on transparent background |

---

## Step 4 — Package into a zip

Run this in PowerShell from the project root:

```powershell
cd teams_app
Compress-Archive -Path manifest.json, color.png, outline.png -DestinationPath mochi-kiki.zip
```

The zip must be flat — no subfolders inside:

```
mochi-kiki.zip
├── manifest.json
├── color.png
└── outline.png
```

---

## Step 5 — Upload to Teams

1. Open the Teams client → left sidebar **Apps** → **Manage your apps** → **Upload an app**
2. Select **Upload a custom app** → choose `teams_app/mochi-kiki.zip`
3. Select the team or channel where you want the bot → click **Add**

> **Note:** Your organization's Teams admin must allow custom app uploads.  
> If blocked: Teams Admin Center → **Teams apps** → **Setup policies** → enable "Upload custom apps"

---

## Step 6 — Verify in a Meeting

1. Start or schedule a new Teams meeting
2. When the meeting starts, a `meetingStart` event is sent to the bot's `/api/messages` endpoint
3. The `ConversationReference` is saved to Cosmos DB
4. Recall.ai joins the meeting and begins transcription
5. When a spec question is detected, a `[Spec Assist]` message is posted to the meeting chat

Check the container app logs to confirm the `meetingStart` event is received:

```powershell
az containerapp logs show --name mochikiki-bot-dev --resource-group <your-rg> --follow
```

---

## Verification Checklist

| Check | How to verify |
|-------|---------------|
| `MICROSOFT_APP_ID` in `.env` is a real UUID | Open `.env` |
| Bot Service messaging endpoint is correct | Azure Portal → Bot → Configuration |
| Teams channel is enabled | Azure Bot → Channels |
| Container app is running | `az containerapp show --name mochikiki-bot-dev ...` |
| Recall bot joins the meeting | `python scripts/test_recall_ws.py` |
| Bot posts to meeting chat | Start a meeting and say a spec question |

---

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `meetingStart` event never arrives | Missing RSC permissions | Check `resourceSpecific` in `manifest.json` |
| 401 Unauthorized errors in logs | Wrong APP_ID or APP_PASSWORD | Regenerate the client secret in Entra |
| Bot does not post to chat | `ConversationReference` not registered | Check container logs for the `meetingStart` event |
| Cannot upload custom app | Admin policy blocks uploads | Enable "Upload custom apps" in Teams Admin Center |
| Recall bot does not join | Bot endpoint unreachable | Verify `RECALL_WS_PUBLIC_URL` in `.env` and container is public |
