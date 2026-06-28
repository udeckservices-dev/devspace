# DevSpace - VPS Deployment (Simplified)

## Step 1: CyberPanel Setup

1. **CyberPanel Install Karein:**
   - Go to: https://cyberpanel.net/
   - Install on your VPS (recommended: Ubuntu 20.04 or 22.04)

2. **Domain Add Karein:**
   - Login to CyberPanel: `https://your-server-ip:8090`
   - Websites â†’ Create Website
   - Add your domain

3. **SSL Enable Karein:**
   - Websites â†’ List Websites
   - Your domain pe click â†’ SSL
   - Free SSL issue karein

---

## Step 2: Server Setup

SSH se connect karein (Putty ya Terminal use karein):

```bash
# Python install karein
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

# MySQL install (agar nahi hai)
sudo apt install -y mysql-server
```

**MySQL Setup:**
```bash
sudo mysql
```

MySQL me ye commands chalayein:
```sql
CREATE DATABASE devspace CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'devspace'@'localhost' IDENTIFIED BY 'YOUR_STRONG_DB_PASSWORD';
GRANT ALL PRIVILEGES ON devspace.* TO 'devspace'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

---

## Step 3: Project Upload

**Option A: Git Se (Recommended)**

```bash
cd /home/yourdomain.com
git clone YOUR_GITHUB_REPO_URL .
```

**Option B: File Manager Se**

1. CyberPanel â†’ File Manager
2. /home/yourdomain.com me jayein
3. zip upload karein aur extract karein

---

## Step 4: Configuration

```bash
cd /home/yourdomain.com

# .env file banayein
nano .env
```

Content:
```env
SECRET_KEY=anyrandomstring123456
FLASK_ENV=production
USE_SQLITE=false
DB_HOST=localhost
DB_PORT=3306
DB_NAME=devspace
DB_USER=devspace
DB_PASSWORD=YOUR_STRONG_DB_PASSWORD
```

---

## Step 5: Python App Setup (CyberPanel Me)

1. **CyberPanel â†’ Websites â†’ List Websites**
2. **Your Domain pe click**
3. **Python Apps â†’ Create Application**

Fill details:
- App Type: `Python`
- App Name: `DevSpace`
- App Root: `/home/yourdomain.com`
- Startup File: `run.py`
- URL: `/`

4. **Save karein**

---

## Step 6: Permissions

```bash
# Ownership set karein
sudo chown -R nobody:nobody /home/yourdomain.com
sudo chown -R nobody:nobody /home/yourdomain.com/venv

# Permissions
chmod -R 755 /home/yourdomain.com
```

---

## Step 7: OpenLiteSpeed Restart

1. **CyberPanel â†’ Websites â†’ List Websites**
2. **Your Domain â†’ Restart**

---

## Step 8: Test

Browser me open karein:
```
https://yourdomain.com
```

**Login Credentials:**
- Email: `admin@example.com`
- Password: `change-this-password`

---

## Agar Issue Aaye

### 502 Error
- Python App properly configure hai?
- Restart LSWS: `sudo systemctl restart lsws`

### Database Error
- MySQL credentials check karein
- Database exist karein: `mysql -u DevSpace -p -e "SHOW DATABASES;"`

### Permission Error
```bash
sudo chown -R nobody:nobody /home/yourdomain.com
```

---

## Quick Checklist

- [ ] CyberPanel installed
- [ ] Domain create kiya
- [ ] SSL enable kiya
- [ ] Files upload kiye
- [ ] .env configure kiya
- [ ] MySQL database banaya
- [ ] Python App setup kiya
- [ ] Permissions set kiye
- [ ] Website restart kiya

---

## Common Commands

```bash
# App restart
sudo systemctl restart lsws

# Logs dekhne ke liye
sudo tail -f /usr/local/lsws/logs/error.log

# Python app manually run karein (testing ke liye)
cd /home/yourdomain.com
source venv/bin/activate
python run.py
```