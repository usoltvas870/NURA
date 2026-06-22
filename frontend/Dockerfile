FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY pwa/ /usr/share/nginx/html/app/
COPY index.html mini.html manifest.json service-worker.js offline.html favicon.ico favicon.png nura-hero.webp /usr/share/nginx/html/
EXPOSE 8080
