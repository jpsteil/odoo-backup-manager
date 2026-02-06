"""Docker template strings for Odoo Docker Export.

All templates use string.Template with $variable substitution.
Shell script variables use $$ to produce literal $ in output.
"""

from string import Template

DOCKER_COMPOSE_TEMPLATE = Template("""\
services:
  db:
    image: postgres:${postgres_version}
    environment:
      POSTGRES_USER: odoo
      POSTGRES_PASSWORD: odoo
      POSTGRES_DB: postgres
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U odoo"]
      interval: 5s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  odoo:
    build:
      context: .
      dockerfile: Dockerfile
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "${odoo_port}:8069"
      - "${longpolling_port}:8072"
    volumes:
      - odoo-filestore:/opt/odoo/filestore
      - ./qlf:/opt/odoo/qlf
      - ./odoo.conf:/opt/odoo/odoo.conf
    environment:
      - DB_HOST=db
      - DB_PORT=5432
      - DB_USER=odoo
      - DB_PASSWORD=odoo
      - DB_NAME=${db_name}
    restart: unless-stopped

  mailpit:
    image: axllent/mailpit:latest
    ports:
      - "${mailpit_http_port}:8025"
    restart: unless-stopped

volumes:
  pgdata:
  odoo-filestore:
""")

DOCKERFILE_TEMPLATE = Template("""\
FROM python:${python_version}-bookworm

# System dependencies for Odoo
RUN apt-get update && apt-get install -y --no-install-recommends \\
    build-essential \\
    libpq-dev \\
    libxml2-dev \\
    libxslt1-dev \\
    libldap2-dev \\
    libsasl2-dev \\
    libjpeg-dev \\
    zlib1g-dev \\
    libfreetype6-dev \\
    liblcms2-dev \\
    libffi-dev \\
    postgresql-client \\
    wkhtmltopdf \\
    node-less \\
    npm \\
    && rm -rf /var/lib/apt/lists/*

# Install rtlcss for RTL support
RUN npm install -g rtlcss

# Create odoo user and directories
RUN useradd -m -d /opt/odoo -s /bin/bash odoo \\
    && mkdir -p /opt/odoo/filestore \\
    && mkdir -p /opt/odoo/qlf \\
    && mkdir -p /opt/odoo/init

# Copy Python requirements and install first (better layer caching)
COPY requirements.txt /opt/odoo/requirements.txt
RUN pip install --no-cache-dir -r /opt/odoo/requirements.txt

# Copy source tree
COPY qlf/ /opt/odoo/qlf/

${copy_extra_files}
# Copy configuration and scripts
COPY odoo.conf /opt/odoo/odoo.conf
COPY entrypoint.sh /opt/odoo/entrypoint.sh
COPY neutralize.sql /opt/odoo/neutralize.sql

# Copy init data (database dump)
COPY init/ /opt/odoo/init/

# Copy filestore archive
COPY filestore.tar.gz /opt/odoo/filestore.tar.gz

# Set permissions
RUN chown -R odoo:odoo /opt/odoo \\
    && chmod +x /opt/odoo/entrypoint.sh

USER odoo
WORKDIR /opt/odoo

EXPOSE 8069 8072

ENTRYPOINT ["/opt/odoo/entrypoint.sh"]
""")

# Note: $$ in Template produces a literal $ in the output.
# Shell variables like $DB_HOST become $$DB_HOST in the template.
ENTRYPOINT_TEMPLATE = Template("""\
#!/bin/bash
set -e

INIT_FLAG="/opt/odoo/filestore/.initialized"
DB_NAME="$${DB_NAME:-${db_name}}"
DB_HOST="$${DB_HOST:-db}"
DB_PORT="$${DB_PORT:-5432}"
DB_USER="$${DB_USER:-odoo}"
DB_PASSWORD="$${DB_PASSWORD:-odoo}"

export PGPASSWORD="$$DB_PASSWORD"

# ---- Wait for PostgreSQL ----
echo "Waiting for PostgreSQL at $$DB_HOST:$$DB_PORT..."
until pg_isready -h "$$DB_HOST" -p "$$DB_PORT" -U "$$DB_USER" -q; do
    sleep 1
done
echo "PostgreSQL is ready."

# ---- First-boot initialization ----
if [ ! -f "$$INIT_FLAG" ]; then
    echo "============================================"
    echo "  First-boot initialization"
    echo "============================================"

    # Step 1: Create database if it doesn't exist
    echo "[1/5] Creating database $$DB_NAME..."
    psql -h "$$DB_HOST" -p "$$DB_PORT" -U "$$DB_USER" -d postgres \\
        -tc "SELECT 1 FROM pg_database WHERE datname = '$$DB_NAME'" | grep -q 1 \\
        || createdb -h "$$DB_HOST" -p "$$DB_PORT" -U "$$DB_USER" "$$DB_NAME"

    # Step 2: Restore database dump
    echo "[2/5] Restoring database from dump..."
    gunzip -c /opt/odoo/init/database.sql.gz | \\
        psql -h "$$DB_HOST" -p "$$DB_PORT" -U "$$DB_USER" -d "$$DB_NAME" -q

    # Step 3: Run neutralization SQL (BEFORE filestore - no lag with un-neutralized data)
    echo "[3/5] Neutralizing database..."
    psql -h "$$DB_HOST" -p "$$DB_PORT" -U "$$DB_USER" -d "$$DB_NAME" \\
        -f /opt/odoo/neutralize.sql -q

    # Step 4: Extract filestore
    echo "[4/5] Extracting filestore..."
    mkdir -p "/opt/odoo/filestore/$$DB_NAME"
    tar -xzf /opt/odoo/filestore.tar.gz --strip-components=1 -C "/opt/odoo/filestore/$$DB_NAME"

    # Step 5: Mark as initialized
    touch "$$INIT_FLAG"
    echo "[5/5] Initialization complete."
    echo "============================================"
fi

unset PGPASSWORD

# ---- Start Odoo ----
echo "Starting Odoo..."
exec python /opt/odoo/qlf/${odoo_subdir}/odoo-bin \\
    --config=/opt/odoo/odoo.conf \\
    --db_host="$$DB_HOST" \\
    --db_port="$$DB_PORT" \\
    --db_user="$$DB_USER" \\
    --db_password="$$DB_PASSWORD" \\
    "$$@"
""")

ODOO_CONF_TEMPLATE = Template("""\
[options]
addons_path = ${addons_path}
data_dir = /opt/odoo
db_host = db
db_port = 5432
db_user = odoo
db_password = odoo
db_name = ${db_name}
admin_passwd = admin
xmlrpc_port = 8069
proxy_mode = False
without_demo = all
smtp_server = mailpit
smtp_port = 1025
email_from = test@example.com
list_db = True
log_level = info
""")
