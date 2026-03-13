# Deploying trafficMCP on Linode

## Prerequisites
- Linode VM: Ubuntu 22.04 LTS, 2 GB RAM minimum (Nanode 2GB or higher)
- Python 3.11+ available on the VM
- Akamai `.edgerc` credential file with a `[default]` section
- `ufw` firewall enabled

---

## 1. Provision the Linode VM

Create a Linode with Ubuntu 22.04 LTS. SSH in as root, then create a dedicated user:

```bash
adduser deploy
usermod -aG sudo deploy
```

---

## 2. Install Python 3.11+

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv python3.11-pip git
```

---

## 3. Deploy the project

```bash
sudo mkdir -p /opt/trafficMCP
sudo chown deploy:deploy /opt/trafficMCP

# As the deploy user:
su - deploy
git clone <your-repo-url> /opt/trafficMCP
cd /opt/trafficMCP

python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

---

## 4. Configure credentials

Copy your local `.edgerc` to the VM:

```bash
# From your local machine:
scp ~/.edgerc deploy@<LINODE_IP>:/home/deploy/.edgerc
```

On the VM, restrict permissions:

```bash
chmod 600 /home/deploy/.edgerc
```

---

## 5. Create the environment file

```bash
cp /opt/trafficMCP/.env.example /opt/trafficMCP/.env
```

Edit `/opt/trafficMCP/.env` and set:
```
EDGERC_PATH=/home/deploy/.edgerc
EDGERC_SECTION=default
MCP_HOST=0.0.0.0
MCP_PORT=8000
LOG_LEVEL=INFO
```

---

## 6. Install and start the systemd service

```bash
sudo cp /opt/trafficMCP/deploy/trafficmcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable trafficmcp
sudo systemctl start trafficmcp

# Verify it is running:
sudo systemctl status trafficmcp
sudo journalctl -u trafficmcp -f
```

---

## 7. Open the firewall

```bash
sudo ufw allow 8000/tcp
sudo ufw reload
```

> **Tip:** For extra security, restrict access to only your Claude Desktop machine's IP:
> ```bash
> sudo ufw allow from <YOUR_IP> to any port 8000
> ```

---

## 8. Configure Claude Desktop

On your local machine, edit `claude_desktop_config.json`
(usually at `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS or
`%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "akamai-traffic": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://<LINODE_IP>:8000/mcp"
      ]
    }
  }
}
```

Restart Claude Desktop. You should now see the Akamai traffic tools available.

---

## Updating the server

```bash
cd /opt/trafficMCP
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart trafficmcp
```

---

## Useful commands

| Action | Command |
|--------|---------|
| View live logs | `sudo journalctl -u trafficmcp -f` |
| Restart server | `sudo systemctl restart trafficmcp` |
| Stop server | `sudo systemctl stop trafficmcp` |
| Check status | `sudo systemctl status trafficmcp` |
