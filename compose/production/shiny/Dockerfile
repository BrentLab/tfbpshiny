# Use a slim Python base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system-level build dependencies
# TODO: can remove git when no dependencies need
# to install from github
# TODO: zlib, lib, liblzma packages can be removed
# if callingcardstools is removed from the deps
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    zlib1g-dev \
    libbz2-dev \
    liblzma-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy metadata first for better caching
COPY pyproject.toml README.md ./
COPY tfbpshiny/ tfbpshiny/
# TODO: remove this when the corr plots are drawn from DB
COPY tmp/shiny_data tmp/shiny_data
COPY configure_logger.py .

# Install runtime dependencies
RUN pip install --no-cache-dir .

# Now copy the rest of the app
COPY . .

# Set the entrypoint
CMD ["python", "-m", "tfbpshiny", "shiny"]
