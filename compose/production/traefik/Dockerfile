FROM traefik:2.10.7

# Improve clarity and permissions handling
RUN mkdir -p /etc/traefik/acme && \
    touch /etc/traefik/acme/acme.json && \
    chmod 600 /etc/traefik/acme/acme.json

# Use COPY with trailing slash for clarity
COPY ./compose/production/traefik/traefik.yml /etc/traefik/traefik.yml
