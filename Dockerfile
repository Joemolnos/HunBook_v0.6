# Python base image
FROM python:3.12-slim

# System deps for WeasyPrint (Cairo/Pango/etc.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libcairo2 \
       pango1.0-tools \
       libpango-1.0-0 \
       libpangocairo-1.0-0 \
       libgdk-pixbuf-2.0-0 \
       libffi-dev \
       fonts-dejavu \
       curl \
    && rm -rf /var/lib/apt/lists/*

# Workdir
WORKDIR /app

# Copy requirements and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Environment
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Expose port
EXPOSE 8000

# Start FastAPI
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
