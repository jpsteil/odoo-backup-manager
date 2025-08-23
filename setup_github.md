# GitHub Setup Instructions for Odoo Backup Tool

## Quick Setup (Copy & Paste)

### Step 1: Create Repository on GitHub
Open your browser and go to: https://github.com/new

Fill in:
- **Repository name:** `odoo-backup-tool`
- **Description:** `A comprehensive backup and restore utility for Odoo instances`
- **Public/Private:** Your choice
- **DON'T** check any initialization options

Click "Create repository"

### Step 2: Push Your Code
After creating the empty repository, copy and run these commands:

```bash
cd /home/jim/dev/odoo-util/odoo_backup_tool

# Add your GitHub repository as origin
git remote add origin https://github.com/jpsteil/odoo-backup-tool.git

# Push your code
git push -u origin main
```

If you prefer SSH (recommended if you have SSH keys set up):
```bash
git remote set-url origin git@github.com:jpsteil/odoo-backup-tool.git
git push -u origin main
```

### Step 3: Verify
Your repository should now be live at:
https://github.com/jpsteil/odoo-backup-tool

## Optional: Using GitHub CLI (if you have it installed)

If you have `gh` CLI installed and authenticated:
```bash
cd /home/jim/dev/odoo-util/odoo_backup_tool
gh repo create odoo-backup-tool --public --source=. --remote=origin --push
```

## After Setup

1. **Add Topics**: Go to your repo settings and add topics: `odoo`, `backup`, `restore`, `postgresql`, `python`

2. **Create a Release** (optional):
```bash
git tag -a v1.0.0 -m "Initial release: Odoo Backup Tool v1.0.0"
git push origin v1.0.0
```

3. **Upload Release Assets**: You can attach the built packages from `dist/` folder to your release

## Troubleshooting

If you get a "repository already exists" error:
```bash
git remote rm origin
git remote add origin https://github.com/jpsteil/odoo-backup-tool.git
git push -u origin main
```

If you need to force push (be careful):
```bash
git push -u origin main --force
```

## Your Repository is Ready! 🎉

Once pushed, your repository will be available at:
https://github.com/jpsteil/odoo-backup-tool