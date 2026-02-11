FROM node:20-alpine AS build
WORKDIR /app

COPY gui/package*.json ./
RUN npm ci

COPY gui/ ./

ARG VITE_GATEWAY_URL
ENV VITE_GATEWAY_URL=${VITE_GATEWAY_URL}

RUN npm run build

FROM nginx:1.27-alpine
COPY automation/gcp_gke/assets/gui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
