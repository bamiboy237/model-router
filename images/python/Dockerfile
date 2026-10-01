# Sandbox image for Python tasks. Sandboxes have no network, so every tool and
# dependency a task needs is installed here.
FROM python:3.12
RUN pip install --no-cache-dir pytest==8.3.5 flask==3.1.3
ENV PYTHONDONTWRITEBYTECODE=1
