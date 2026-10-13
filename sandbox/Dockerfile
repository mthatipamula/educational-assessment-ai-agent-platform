FROM python:3.12-slim
RUN useradd --system --uid 10001 sandbox
WORKDIR /srv
COPY runner.py .
USER 10001
ENV PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp
EXPOSE 8080
CMD ["python3", "-I", "runner.py"]
