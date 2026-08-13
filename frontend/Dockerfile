FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .

# vite แทนค่า import.meta.env ตอน build ไม่ใช่ตอน run — ต้องส่งเข้ามาก่อนบิลด์
# prod ส่ง "/api" มาให้ (ดู docker-compose.prod.yml) จะได้ไม่ฝัง IP ลงไฟล์ JS
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
