#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== PyPI Deployment for Odoo Backup Tool ===${NC}"
echo ""

# Check if in virtual environment
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo -e "${YELLOW}Activating virtual environment...${NC}"
    source venv/bin/activate
fi

# Check packages
echo -e "${GREEN}Packages ready for upload:${NC}"
ls -lh dist/*.tar.gz dist/*.whl
echo ""

# Ask for deployment target
echo -e "${YELLOW}Where would you like to deploy?${NC}"
echo "1) TestPyPI (recommended for first time)"
echo "2) PyPI (production)"
echo "3) Cancel"
read -p "Enter choice [1-3]: " choice

case $choice in
    1)
        echo ""
        echo -e "${BLUE}Uploading to TestPyPI...${NC}"
        echo -e "${YELLOW}Note: You'll need a TestPyPI account and token${NC}"
        echo -e "Get token at: https://test.pypi.org/manage/account/token/"
        echo ""
        echo "When prompted:"
        echo "  Username: __token__"
        echo "  Password: [your-testpypi-token]"
        echo ""
        twine upload --repository testpypi dist/*
        
        if [ $? -eq 0 ]; then
            echo ""
            echo -e "${GREEN}✅ Successfully uploaded to TestPyPI!${NC}"
            echo -e "View at: ${BLUE}https://test.pypi.org/project/odoo-backup-tool/${NC}"
            echo ""
            echo "Test installation with:"
            echo -e "${YELLOW}pip install -i https://test.pypi.org/simple/ odoo-backup-tool${NC}"
        fi
        ;;
    2)
        echo ""
        echo -e "${BLUE}Uploading to PyPI...${NC}"
        echo -e "${YELLOW}Note: You'll need a PyPI account and token${NC}"
        echo -e "Get token at: https://pypi.org/manage/account/token/"
        echo ""
        echo "When prompted:"
        echo "  Username: __token__"
        echo "  Password: [your-pypi-token]"
        echo ""
        read -p "Are you sure you want to upload to production PyPI? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            twine upload dist/*
            
            if [ $? -eq 0 ]; then
                echo ""
                echo -e "${GREEN}✅ Successfully uploaded to PyPI!${NC}"
                echo -e "View at: ${BLUE}https://pypi.org/project/odoo-backup-tool/${NC}"
                echo ""
                echo "Install with:"
                echo -e "${YELLOW}pip install odoo-backup-tool${NC}"
            fi
        else
            echo -e "${YELLOW}Upload cancelled.${NC}"
        fi
        ;;
    3)
        echo -e "${YELLOW}Deployment cancelled.${NC}"
        exit 0
        ;;
    *)
        echo -e "${RED}Invalid choice. Exiting.${NC}"
        exit 1
        ;;
esac