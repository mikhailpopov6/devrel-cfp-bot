# DevRel CFP Bot

A Telegram bot that reminds people about CFP (call for papers) deadlines of IT conferences. Users subscribe to the conference categories they care about and get notified in Telegram before submissions close.

The conference list lives in a Google Sheet, so the DevRel team updates it without touching the code.

## Features

- Subscriptions by category: Backend, Frontend, QA and any others you add to the sheet
- Reminders a week and a day before a CFP closes, checked daily at 09:00 server time
- `/my_conferences` lists open CFPs for your subscriptions
- Admin commands: subscriber stats and manual notifications for a category

## Requirements

- Python 3.8+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Google Cloud service account with read access to the sheet

## Setup

### 1. Install

```bash
git clone https://github.com/mikhailpopov6/devrel-cfp-bot.git
cd devrel-cfp-bot
pip install -r requirements.txt
```

### 2. Configure `config.json`

The repository contains a template. Fill it in on your server:

```json
{
    "bot_token": "<YOUR_TELEGRAM_BOT_TOKEN>",
    "spreadsheet_id": "<GOOGLE_SHEET_ID>",
    "range_name": "A2:C100",
    "admin_ids": [123456789]
}
```

- `bot_token` — your bot token from @BotFather
- `spreadsheet_id` — ID of the Google Sheet with conferences
- `range_name` — data range; keep the default unless your sheet differs
- `admin_ids` — Telegram user IDs of admins (you can get yours from @userinfobot)

### 3. Add `credentials.json`

`credentials.json` in the repository is an empty template. On the server, replace it with the full service account key you download from Google Cloud (see below). Never commit the real key.

## Google Sheet

### Create the sheet

Create a sheet with these columns in the first row:

| Name | Start date | CFP deadline | Categories | Link |
|---|---|---|---|---|
| DevConf Moscow | 15.09.2024 | 01.08.2024 | Backend, Frontend | https://devconf.ru |
| QA Days | 10.10.2024 | 20.08.2024 | QA, Testing | https://qadays.ru |

- Dates use the `DD.MM.YYYY` format.
- Separate categories with a comma and a space: `Backend, Frontend`.
- The sheet ID is the part of the URL between `/d/` and `/edit`.
- Share the sheet with the service account email (read access is enough).

### Get a service account key

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create or pick a project.
2. Go to **APIs & Services → Credentials → Create credentials → Service account**.
3. Enter a name, click **Create and continue**, then **Done** (project roles are optional).
4. Open the new service account, go to **Keys → Add key → Create new key → JSON**.
5. Save the downloaded file as `credentials.json` next to the bot.
6. Use the service account email (for example `my-bot@my-project.iam.gserviceaccount.com`) to share the sheet.

## Run

Initialize the subscriptions database once:

```bash
python3 -c "from cfp_bot import init_db; init_db()"
```

Start the bot:

```bash
python cfp_bot.py
```

## Commands

For everyone:

- `/start` — welcome message
- `/subscribe` — subscribe to conference categories
- `/my_conferences` — open CFPs for your subscriptions
- `/help` — help

For admins:

- `/subscribers` — subscriber stats by category
- `/notify` — send a CFP notification for a chosen category

The bot talks to users in Russian: it was built for Russian-speaking IT conferences.
