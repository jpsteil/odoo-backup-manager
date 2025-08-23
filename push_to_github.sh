#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Setting up GitHub repository for Odoo Backup Tool${NC}"
echo ""

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo -e "${YELLOW}GitHub CLI (gh) is not installed.${NC}"
    echo "Install it with: sudo apt install gh"
    echo "Or visit: https://cli.github.com/"
    exit 1
fi

# Check if authenticated with GitHub
if ! gh auth status &> /dev/null; then
    echo -e "${YELLOW}You need to authenticate with GitHub first.${NC}"
    echo "Run: gh auth login"
    exit 1
fi

# Create the repository on GitHub
echo -e "${GREEN}Creating repository on GitHub...${NC}"
gh repo create odoo-backup-tool \
    --public \
    --description "A comprehensive backup and restore utility for Odoo instances" \
    --source=. \
    --remote=origin \
    --push

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ Success! Your repository has been created and pushed to GitHub!${NC}"
    echo ""
    echo -e "Repository URL: ${GREEN}https://github.com/$(gh api user -q .login)/odoo-backup-tool${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Visit your repository on GitHub"
    echo "2. Add topics: odoo, backup, postgresql, python"
    echo "3. Create a release if desired"
    echo "4. Star your own repository! ⭐"
    
    # Open the repository in browser
    echo ""
    read -p "Would you like to open the repository in your browser? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        gh repo view --web
    fi
else
    echo -e "${RED}Failed to create repository. Please check the error message above.${NC}"
    exit 1
fi