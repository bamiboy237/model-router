# Sandbox image for frontend tasks. Packages are linked at /node_modules, which Node
# finds from /work by walking up parent directories, so the checkout needs no install.
FROM node:22
WORKDIR /deps
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund && chmod -R a+rX /deps && ln -s /deps/node_modules /node_modules
ENV PATH="/deps/node_modules/.bin:${PATH}"
WORKDIR /
