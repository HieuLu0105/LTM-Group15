# NetPulse Hardware Maximum + Telegram Private

## Run on Windows (PowerShell)

```powershell
py -m pip install -r requirements.txt
$env:TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN"
$env:TELEGRAM_CHAT_ID="YOUR_PRIVATE_CHAT_ID"
py app.py
```

Open the printed localhost URL, click **Hardware**, configure alert rules and click **Save thresholds**. Click **Send Telegram test** to verify delivery. First send `/start` to your Telegram bot. Never commit the token to Git or post it in screenshots. For persistent setup use Windows user environment variables (restart terminal afterwards), or set them in the launching PowerShell session. A `.env` file is **not automatically loaded**.

## Optional sensors on Windows

The original NetPulse already reads CPU/RAM/disk usage through psutil, GPU readings via NVIDIA `nvidia-smi`, and inventory via Windows CIM. For additional temperature/voltage/fan readings, run LibreHardwareMonitor with its WMI sensor interface available at `root\\LibreHardwareMonitor`. Sensor discovery is best effort: WMI permissions and hardware support vary. The dashboard shows `N/A` when sensors are unavailable; it does not fabricate measurements. GPU temperature can still come from `nvidia-smi`.

## Alerts

- Modes: `instant` sends on first crossing; `sustained` sends only after the configured number of seconds above threshold.
- Cooldown limits repeated new alerts. One alert per incident; Recovery is emitted after falling below the threshold with a small hysteresis margin.
- Thresholds persist at `%USERPROFILE%\\.netpulse\\alert_config.json`, **not** the source's example config. The Telegram token and chat ID are read from environment variables.
- Notifications are asynchronous; a Telegram failure is printed to the console and does not stop network monitoring.
- A reboot clears in-memory alert state. Sensors may be unavailable until LibreHardwareMonitor starts.

## Added endpoints

- `GET /api/hardware` detailed live data, inventory and sensors
- `GET /api/alerts` current thresholds and Telegram configuration status (never returns credentials)
- `POST /api/alerts` save all alert rules
- `POST /api/telegram/test` send a test message

The app binds only to `127.0.0.1` by default. Do not expose these configuration endpoints publicly without authentication.

## Validation

```powershell
py -m compileall -q app.py alerts sensors.py
py app.py
```

Open Hardware, confirm readings and alert form. Test Telegram. Temporarily lower a threshold to trigger a notification and restore it afterwards. Keep the application running to receive alerts.
