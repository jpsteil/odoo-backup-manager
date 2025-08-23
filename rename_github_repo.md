# Rename GitHub Repository

## Steps to rename your GitHub repository:

1. **Go to your repository settings:**
   https://github.com/jpsteil/odoo-backup-tool/settings

2. **In the "General" section at the top:**
   - Find "Repository name" field
   - Change from `odoo-backup-tool` to `odoo-backup-manager`
   - Click "Rename"

3. **GitHub will automatically:**
   - Set up redirects from the old name
   - Update your repository URL

4. **Update your local repository URL:**
   ```bash
   cd /home/jim/dev/odoo-util/odoo_backup_tool
   git remote set-url origin git@github.com-jpsteil:jpsteil/odoo-backup-manager.git
   ```

5. **Verify the change:**
   ```bash
   git remote -v
   ```

## After Renaming:

Your repository will be available at:
- New URL: https://github.com/jpsteil/odoo-backup-manager
- Old URL will redirect automatically

## PyPI Package Info:

Your package is live at: https://pypi.org/project/odoo-backup-manager/

Users can install with:
```bash
pip install odoo-backup-manager
```

## Update GitHub Release:

After renaming, update your v1.0.0 release to include the new distribution files with the correct package name.