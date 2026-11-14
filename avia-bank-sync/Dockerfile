# AVIA Bank Sync — servicio API + scheduler
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=America/Santiago \
    AVIA_CHROMIUM_PATH=/usr/bin/chromium AVIA_BROWSER_HEADLESS=false HOME=/tmp \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# Chromium real + pantalla virtual para el login asistido de portales bancarios.
# Navegador estándar: sin plugins "stealth" ni identidad falseada.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata tini \
        chromium xvfb xauth fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1001 avia && useradd --uid 1001 --gid avia --no-create-home avia

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY avia ./avia
COPY database ./database

USER avia
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--"]
# Un solo proceso: API + scheduler (el lock de PostgreSQL impide ejecuciones simultáneas)
# xvfb-run: Chromium con ventana real dentro de una pantalla virtual
CMD ["xvfb-run", "-a", "-s", "-screen 0 1280x800x24", "uvicorn", "avia.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header"]
