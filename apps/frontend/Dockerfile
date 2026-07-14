# Frontend image — multi-stage: build the Vite SPA, then serve it with nginx.
#
# IMPORTANT: build from the REPO ROOT, not this directory, because the frontend
# depends on the workspace package @indexcards/shared-types:
#
#   docker build -f apps/frontend/Dockerfile -t indexcards-frontend .
#
# This image is an alternative to the compose example in docs/DEPLOYMENT.md,
# which instead mounts a host-built ./apps/frontend/dist into the Caddy proxy.
# Use whichever fits your deployment; do not use both for the same site.

# ---- build stage -------------------------------------------------------------
FROM node:20-bookworm-slim AS build
WORKDIR /repo

# VITE_API_TOKEN is baked into the bundle at build time. Pass it with
# --build-arg VITE_API_TOKEN=... when the backend AUTH_TOKEN is set.
ARG VITE_API_TOKEN=""
ENV VITE_API_TOKEN=${VITE_API_TOKEN}

# Install workspace deps first (cached until any manifest changes).
COPY package.json package-lock.json ./
COPY apps/frontend/package.json apps/frontend/
COPY packages/shared-types/package.json packages/shared-types/
RUN npm ci

# Copy the sources needed to generate shared types and build the frontend.
COPY packages/shared-types packages/shared-types
COPY apps/frontend apps/frontend

# shared-types must be generated before the frontend typechecks/builds.
RUN npm run build --workspace @indexcards/shared-types \
 && npm run build --workspace @indexcards/frontend

# ---- serve stage -------------------------------------------------------------
FROM nginx:1.27-alpine AS serve
# SPA routing: fall back to index.html for client-side routes.
COPY apps/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/frontend/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
