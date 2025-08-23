#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}✅ Tag v1.0.0 has been created and pushed!${NC}"
echo ""
echo -e "${BLUE}Now, let's complete the GitHub setup:${NC}"
echo ""
echo "Opening GitHub pages in your browser..."
echo ""

# Function to open URL
open_url() {
    if command -v xdg-open > /dev/null; then
        xdg-open "$1" 2>/dev/null
    elif command -v open > /dev/null; then
        open "$1"
    else
        echo "Please open manually: $1"
    fi
}

echo -e "${YELLOW}1. CREATE A RELEASE:${NC}"
echo "   - Click 'Draft a new release'"
echo "   - Choose tag: v1.0.0"
echo "   - Release title: 'v1.0.0 - Initial Release'"
echo "   - Attach these files from dist/ folder:"
echo "     • odoo_backup_tool-1.0.0-py3-none-any.whl"
echo "     • odoo_backup_tool-1.0.0.tar.gz"
echo "   - Add release notes about the neutralization feature"
echo ""
open_url "https://github.com/jpsteil/odoo-backup-tool/releases/new"
sleep 2

echo -e "${YELLOW}2. ADD REPOSITORY TOPICS:${NC}"
echo "   - Click the gear icon next to 'About'"
echo "   - Add topics: odoo, backup, restore, postgresql, python, database, tkinter"
echo ""
open_url "https://github.com/jpsteil/odoo-backup-tool"
sleep 2

echo -e "${YELLOW}3. STAR YOUR REPOSITORY:${NC}"
echo "   - Click the Star button to help with visibility!"
echo ""

echo -e "${GREEN}Your repository is live at:${NC}"
echo -e "${BLUE}https://github.com/jpsteil/odoo-backup-tool${NC}"
echo ""

# List the distribution files
echo -e "${YELLOW}Distribution files to upload to release:${NC}"
ls -lh dist/*.tar.gz dist/*.whl 2>/dev/null

echo ""
echo -e "${GREEN}Setup complete! Don't forget to:${NC}"
echo "  1. Create the release on GitHub"
echo "  2. Upload the distribution files"
echo "  3. Add repository topics"
echo "  4. Star your repository ⭐"