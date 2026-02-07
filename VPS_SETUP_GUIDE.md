# Trading Bot VPS Setup Guide

Complete setup guide for a fresh Ubuntu VPS.

## 📋 Requirements

- Ubuntu 22.04 or 24.04 LTS
- Minimum 1GB RAM, 1 CPU
- Recommended: 2GB RAM, 1 CPU
- Location: US East Coast (NYC, Virginia, New Jersey)

---

## 🚀 Step 1: Initial Server Setup

### 1.1 Connect to your VPS
```bash
ssh root@YOUR_VPS_IP
```

### 1.2 Update system
```bash
apt update && apt upgrade -y
```

### 1.3 Create a trading user (don't run as root!)
```bash
# Create user
adduser trader
# Add to sudo group
usermod -aG sudo trader
# Switch to new user
su - trader
```

### 1.4 Set timezone to New York
```bash
sudo timedatectl set-timezone America/New_York
# Verify
date
```

---

## 🐍 Step 2: Install Python

### 2.1 Install Python 3.11+ and tools
```bash
sudo apt install -y python3 python3-pip python3-venv git curl
```

### 2.2 Verify Python version
```bash
python3 --version
# Should be 3.10 or higher
```

---

## 📦 Step 3: Download & Setup Bot

### 3.1 Create directory
```bash
mkdir -p ~/tradingbot
cd ~/tradingbot
```

### 3.2 Upload the bot files
**Option A: Using scp from your local machine:**
```bash
# Run this from YOUR computer, not the VPS
scp trading_bot_v10.zip trader@YOUR_VPS_IP:~/tradingbot/
```

**Option B: Using wget if hosted somewhere:**
```bash
wget YOUR_DOWNLOAD_URL -O trading_bot_v10.zip
```

### 3.3 Extract files
```bash
cd ~/tradingbot
unzip trading_bot_v10.zip
mv trading_bot/* .
rm -rf trading_bot trading_bot_v10.zip
```

### 3.4 Create virtual environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3.5 Install dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.6 Verify installation
```bash
python check_setup.py
```

---

## 🔑 Step 4: Configure API Keys

### 4.1 Create .env file
```bash
cp .env.example .env
nano .env
```

### 4.2 Fill in your API keys
```env
# Trading212 API
T212_API_KEY=your_trading212_api_key_here
T212_PAPER_MODE=true

# Telegram Bot
TELEGRAM_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Financial Modeling Prep (for earnings)
FMP_API_KEY=your_fmp_api_key

# MongoDB (optional - leave empty to use JSON files)
MONGO_URI=
```

Save: `Ctrl+X`, then `Y`, then `Enter`

### 4.3 Get your API keys

**Trading212:**
1. Login to Trading212
2. Go to Settings → API
3. Generate new API key
4. For testing, use the DEMO/PAPER account key

**Telegram:**
1. Message @BotFather on Telegram
2. Send `/newbot` and follow instructions
3. Copy the token
4. To get chat ID: message @userinfobot

**FMP (Financial Modeling Prep):**
1. Go to https://financialmodelingprep.com/
2. Sign up for free account
3. Copy API key from dashboard

---

## ✅ Step 5: Verify Everything Works

### 5.1 Run setup check
```bash
cd ~/tradingbot
source venv/bin/activate
python check_setup.py
```

All items should show ✓

### 5.2 Test connections
```bash
python main.py --test
```

### 5.3 Test trade execution (PAPER MODE!)
```bash
python -m tests.test_trade_execution --status
```

### 5.4 Test a small trade
```bash
python -m tests.test_trade_execution --symbol AAPL --amount 10
```

---

## 🔄 Step 6: Setup Auto-Start with systemd

### 6.1 Create service file
```bash
sudo nano /etc/systemd/system/tradingbot.service
```

### 6.2 Paste this content
```ini
[Unit]
Description=Trading Bot
After=network.target

[Service]
Type=simple
User=trader
WorkingDirectory=/home/trader/tradingbot
Environment=PATH=/home/trader/tradingbot/venv/bin
ExecStart=/home/trader/tradingbot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Save and exit.

### 6.3 Enable and start service
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable tradingbot

# Start the bot
sudo systemctl start tradingbot

# Check status
sudo systemctl status tradingbot
```

### 6.4 Useful commands
```bash
# View logs
sudo journalctl -u tradingbot -f

# Stop bot
sudo systemctl stop tradingbot

# Restart bot
sudo systemctl restart tradingbot

# Disable auto-start
sudo systemctl disable tradingbot
```

---

## 📱 Step 7: Verify Telegram Works

After starting the bot, send these commands in Telegram:

```
/help     - See all commands
/status   - Check bot status
/balance  - See account balance
```

---

## 🔒 Step 8: Security (Optional but Recommended)

### 8.1 Setup firewall
```bash
sudo ufw allow OpenSSH
sudo ufw enable
```

### 8.2 Disable root login
```bash
sudo nano /etc/ssh/sshd_config
# Change: PermitRootLogin no
sudo systemctl restart sshd
```

### 8.3 Setup SSH keys (do this before disabling password auth!)
```bash
# On your LOCAL machine, generate key:
ssh-keygen -t ed25519

# Copy to server:
ssh-copy-id trader@YOUR_VPS_IP
```

---

## 📊 Step 9: Monitor the Bot

### View live logs
```bash
sudo journalctl -u tradingbot -f
```

### Check bot files
```bash
cd ~/tradingbot
ls -la data/     # Analysis files
ls -la logs/     # Log files
```

### Telegram commands for monitoring
```
/status      - Bot status
/positions   - Open positions
/balance     - Account balance
/trades      - Today's trades
/pause       - Pause trading
/resume      - Resume trading
```

---

## 🗓 Step 10: Weekly Schedule

The bot runs automatically:

| Day | Time (ET) | Activity |
|-----|-----------|----------|
| Saturday | 10:00 AM | Weekend analysis starts |
| Sunday | All day | Analysis continues |
| Monday-Friday | 9:00 AM | Pre-market scans |
| Monday-Friday | 9:30 AM | Market open, trading active |
| Monday-Friday | 4:00 PM | Market close |
| Monday-Friday | 4:05 PM | Daily summary sent |

---

## 🆘 Troubleshooting

### Bot not starting?
```bash
# Check status
sudo systemctl status tradingbot

# Check logs
sudo journalctl -u tradingbot --no-pager -n 50
```

### Yahoo Finance blocked?
Test with:
```bash
curl -I https://query1.finance.yahoo.com/v8/finance/chart/AAPL
```
- 200 = OK
- 429 = Rate limited (wait or change VPS)

### API connection issues?
```bash
cd ~/tradingbot
source venv/bin/activate
python main.py --test
```

### Telegram not responding?
1. Make sure bot is running: `sudo systemctl status tradingbot`
2. Check TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env
3. Make sure you started a chat with your bot first

---

## 📝 Quick Reference

```bash
# Activate environment
cd ~/tradingbot && source venv/bin/activate

# Run bot manually (for testing)
python main.py

# Run tests
python main.py --test
python check_setup.py

# Service commands
sudo systemctl start tradingbot
sudo systemctl stop tradingbot
sudo systemctl restart tradingbot
sudo systemctl status tradingbot

# View logs
sudo journalctl -u tradingbot -f
```

---

## ✅ Checklist Before Going Live

- [ ] VPS in US East Coast location
- [ ] Python 3.10+ installed
- [ ] All dependencies installed (check_setup.py passes)
- [ ] .env file configured with all API keys
- [ ] Trading212 API works (python main.py --test)
- [ ] Telegram bot responds to /help
- [ ] Test trade executed successfully (paper mode)
- [ ] systemd service running
- [ ] Firewall enabled

**Ready to trade!** 🚀
