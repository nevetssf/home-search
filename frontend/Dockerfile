FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# Build once, then serve the static bundle with Vite's preview server.
RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "preview"]
