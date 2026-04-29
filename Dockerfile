FROM python:3.11-slim

ARG http_proxy
ARG https_proxy

ENV http_proxy=$http_proxy
ENV https_proxy=$https_proxy

WORKDIR /app
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "main.py"]