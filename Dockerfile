# syntax=docker/dockerfile:1.9
# https://hynek.me/articles/docker-uv/
FROM ubuntu:noble AS build

SHELL ["sh", "-exc"]

### Start build prep.
### This should be a separate build container for better reuse.

RUN <<EOT
apt-get update -qy
apt-get install -qyy \
    -o APT::Install-Recommends=false \
    -o APT::Install-Suggests=false \
    build-essential \
    ca-certificates \
    python3-setuptools \
    python3.12-dev
EOT

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# - Silence uv complaining about not being able to use hard links,
# - tell uv to byte-compile packages for faster application startups,
# - prevent uv from accidentally downloading isolated Python builds,
# - pick a Python (use `/usr/bin/python3.12` on uv 0.5.0 and later),
# - and finally declare `/app` as the target for `uv sync`.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.12 \
    UV_PROJECT_ENVIRONMENT=/app

### End build prep -- this is where your app Dockerfile should start.

# Since there's no point in shipping lock files, we move them
# into a directory that is NOT copied into the runtime image.
# The trailing slash makes COPY create `/_lock/` automagically.
COPY pyproject.toml /_lock/
COPY uv.lock /_lock/

# Synchronize DEPENDENCIES without the application itself.
# This layer is cached until uv.lock or pyproject.toml change.
# You can create `/app` using `uv venv` in a separate `RUN`
# step to have it cached, but with uv it's so fast, it's not worth
# it, so we let `uv sync` create it for us automagically.
RUN --mount=type=cache,target=/root/.cache <<EOT
cd /_lock
uv sync \
    --locked \
    --no-dev \
    --no-install-project
EOT

# Now install the APPLICATION from `/src` without any dependencies.
# `/src` will NOT be copied into the runtime container.
# LEAVE THIS OUT if your application is NOT a proper Python package.
# As of uv 0.4.11, you can also use
# `cd /src && uv sync --locked --no-dev --no-editable` instead.
COPY . /src
RUN --mount=type=cache,target=/root/.cache \
    uv pip install \
    --python=$UV_PROJECT_ENVIRONMENT \
    --no-deps \
    /src


##########################################################################

FROM ubuntu:noble
SHELL ["sh", "-c"]

ENV PATH=/app/bin:$PATH

# Don't run your app as root.
RUN <<EOT
groupadd -r app
useradd -r -d /app -g app -N app
EOT

STOPSIGNAL SIGINT

# Note how the runtime dependencies differ from build-time ones.
# Notably, there is no uv either!
RUN <<EOT
apt-get update -qy
apt-get install -qyy \
    -o APT::Install-Recommends=false \
    -o APT::Install-Suggests=false \
    python3.12 \
    libpython3.12 \
    libpcre3 \
    libxml2 \
    cron

apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
EOT

# Copy the pre-built `/app` directory to the runtime container
# and change the ownership to user app and group app in one step.
COPY --from=build --chown=app:app /app /app
COPY ./src /app/
WORKDIR /app

# Create a cron file with the schedule
RUN echo "* * * * * root /app/bin/python /app/janitor.py > /proc/1/fd/1 2>/proc/1/fd/2" | tee /etc/cron.d/janitor-cron
RUN chmod 0644 /etc/cron.d/janitor-cron
RUN chmod 0744 /app/janitor.py
RUN mkdir -p /var/run/ && chown app:app /var/run/
RUN touch /var/log/cron.log && chown app:app /var/log/cron.log

ENV QBIT_IP=localhost
ENV QBIT_PORT=8080
ENV QBIT_LOGIN=""
ENV QBIT_PASSWORD=""
ENV QBIT_CLEANUP_MIN_LEFT_SPACE_GIB=6.0

# https://stackoverflow.com/questions/27771781/how-can-i-access-docker-set-environment-variables-from-a-cron-job
RUN printenv | grep -v "no_proxy" > /etc/environment

RUN <<EOT
python -V
python -Im site
EOT

CMD ["cron", "-f"]