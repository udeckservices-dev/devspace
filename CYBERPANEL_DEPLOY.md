# DevSpace - Local Testing & Deployment Guide

---

## Local Testing with Git

### Step 1: Clone the Project
```bash
git clone <your-repo-url> devspace
cd devspace
```

### Step 2: Install Dependencies
```bash
# Windows
pip install -r requirements.txt

# Linux/Mac
pip3 install -r requirements.txt
```

### Step 3: Configure Environment
```bash
# Copy example env file
copy .env.example .env

# Edit .env with your settings (SQLite for local testing)
```

### Step 4: Run the App
```bash
python run.py
```

### Step 5: Access
- Open browser: http://127.0.0.1:5000
- Login: `uditroy@udeckservices.com` / `admin123`

---

## Testing Deployment with a Git Repository

### Create a Test Git Repository
1. Create a new repo on GitHub/GitLab
2. Add a sample project with requirements.txt

### Add Project in DevSpace
1. Go to Projects â†’ Add Project
2. Fill details:
   - Name: `my-test-project`
   - Repository URL: `https://github.com/yourusername/your-repo.git`
   - Branch: `main`
   - Language: `python`
   - Deploy Path: `C:\test-deploy` (Windows) or `/var/www/test` (Linux)

### Test Deployment
1. Click "Deploy" button
2. Watch the deployment logs
3. Verify files are pulled to deploy path

---

## Testing with Different Languages

### Python Project
Create `requirements.txt`:
```
flask==3.0.0
requests==2.31.0
```

### Node.js Project
Create `package.json` with dependencies.

### PHP Project
Any PHP files will work - just git pull.

---

## Troubleshooting

### Port Already in Use
```bash
# Windows - kill process on port 5000
netstat -ano | findstr :5000
taskkill /PID <PID> /F

# Linux
lsof -i :5000
kill -9 <PID>
```

### Database Issues
```bash
# Delete SQLite database and recreate
del devspace.db
python run.py
```

### Git Authentication Issues
For private repos, use:
- HTTPS with token: `https://oauth2:TOKEN@github.com/user/repo.git`
- Or SSH URL with configured SSH keys