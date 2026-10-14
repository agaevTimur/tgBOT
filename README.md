## 1. Get a bot token
1. In Telegram, open a chat with **@BotFather**.
2. Send `/newbot`, then pick a display name and a username ending in `bot`.
3. BotFather replies with a token like `123456789:AAH...`. Keep it secret.

## 2. Install
Needs Python 3.10 or newer.
```bash
cd telegram-bot
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Run
```bash
export BOT_TOKEN="123456789:AAH..."   # Windows PowerShell: $env:BOT_TOKEN="123456789:AAH..."
python bot.py
```
Keep the terminal open; the bot works while the script runs.

## How it works in the chat
1. Send a photo (or several, an album works too). Images sent as files keep full quality.
2. The bot asks **"Is that all?"** Tap *Add more* or just send more photos. Tap *Yes, that's all* (or type "yes").
3. The bot asks what to name the PDF. Type a name, e.g. `Trip receipts`.
4. You get `Trip receipts.pdf`.

`/cancel` throws away the current photos; `/start` begins fresh.

## Notes
- Photos are kept in memory per user until the PDF is sent, so restarting the bot clears unfinished sessions.
- Up to 100 photos per PDF. Telegram limits bots to sending files of 50 MB.
