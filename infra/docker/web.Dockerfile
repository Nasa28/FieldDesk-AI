FROM node:20-alpine AS deps
WORKDIR /app
COPY apps/web/package.json ./
RUN npm install --no-audit --no-fund

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web ./
RUN npm run build

FROM node:20-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "run", "start"]
