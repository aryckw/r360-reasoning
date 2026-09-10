# r360-reasoning image: gate and service.
#
# Python only. Raw IQ and DSP are out of scope for this service, and the dependency list
# is one of the places that boundary is visible: there is no array or signal-processing
# library here, and tests/test_repository_boundaries.py fails if one appears.
FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171 AS toolchain

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3=3.11.2-1+b1 \
      python3-venv=3.11.2-1+b1 \
      make \
      git \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt
ENV PATH="/opt/venv/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1

RUN git config --global --add safe.directory '*'

WORKDIR /work

# ── service image ────────────────────────────────────────────────────────────
# The gate target above is used with the source bind-mounted. This target ships a
# self-contained image for the composed stack.
FROM toolchain AS service

COPY . /work
ENV PYTHONPATH=/work/generated/python:/work/src

CMD ["python", "-m", "r360_reasoning.service", "--config", "/work/configs/service.dev.json"]
