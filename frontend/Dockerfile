# ---- 构建阶段：tsc + vite build ----
FROM docker.1ms.run/library/node:20-alpine AS build
ARG NPM_REGISTRY=https://registry.npmmirror.com
WORKDIR /app
COPY package*.json ./
RUN npm config set registry ${NPM_REGISTRY} && npm ci
COPY . .
RUN npm run build   # = tsc && vite build

# ---- 运行阶段：nginx 托管静态产物 + 反代 API ----
FROM docker.1ms.run/library/nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
