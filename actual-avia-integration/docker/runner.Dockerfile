# AVIA Actual Runner. Contexto: build/runner-ctx (la prepara build-images.sh): actual/ = fuente parcheada, runner/ = este runner.
FROM node:24.22.1-bookworm AS api
WORKDIR /src
COPY actual/ .
ENV NODE_OPTIONS=--max_old_space_size=8192
RUN git -c init.defaultBranch=master init -q && git add -A && \
    git -c user.email=b@d -c user.name=b commit -qm build && \
    yarn install --immutable && yarn build:api && \
    mkdir -p /out && yarn workspace @actual-app/api pack --out /out/actual-app-api.tgz

FROM node:24.22.1-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1001 avia && useradd --uid 1001 --gid avia -m avia && mkdir /data && chown avia:avia /data
WORKDIR /app
COPY --from=api /out/*.tgz ./vendor/actual-app-api.tgz
COPY runner/package.json runner/index.mjs ./
RUN npm install --omit=dev --no-audit --no-fund && chown -R avia:avia /app
USER avia
ENV NODE_ENV=production
EXPOSE 8090
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "index.mjs"]
