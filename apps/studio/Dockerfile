# Development image only (dev server + hot reload), not a production
# build — see docker-compose.yml. Build context is the repo root (not
# apps/studio) because this app's tsconfig extends
# packages/config/tsconfig.base.json, the shared base every app in this
# monorepo extends; only that package plus this app are copied in.
FROM node:24-slim
WORKDIR /repo
RUN corepack enable

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml turbo.json ./
COPY packages/config ./packages/config
COPY apps/studio ./apps/studio

RUN pnpm install --filter @generate-web-ai/studio...

WORKDIR /repo/apps/studio
EXPOSE 5173
CMD ["pnpm", "dev", "--", "--host", "0.0.0.0"]
