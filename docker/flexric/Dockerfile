FROM debian:bookworm-slim AS builder

ARG BUILD_JOBS=2
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake pkg-config git \
    autoconf automake libtool bison libpcre2-dev \
    libsctp-dev python3 python3-dev swig \
    libconfig-dev libconfig++-dev default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY flexric/ /src/flexric/
COPY test/xapp/ /src/test/xapp/

RUN cmake -S /src/flexric -B /build/flexric \
    -DCMAKE_BUILD_TYPE=Debug \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DE2AP_VERSION=E2AP_V2 \
    -DKPM_VERSION=KPM_V3_00 \
    -DXAPP_DB=MYSQL_XAPP \
    -DUNIT_TEST=OFF \
    -DBUILD_OAI_PI_XAPP_DEMOS=ON \
    && cmake --build /build/flexric --parallel "${BUILD_JOBS}" \
    && DESTDIR=/stage cmake --install /build/flexric \
    && install -D -m 755 \
       /build/flexric/oai-pi-xapp/xapp_handover_control \
       /stage/usr/local/bin/flexric/xApp/c/xapp_handover_control

FROM debian:bookworm-slim AS runtime

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 libpython3.11 libsctp1 libconfig9 libconfig++9v5 libmariadb3 \
    libstdc++6 libgcc-s1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /stage/usr/local/ /usr/local/
RUN ldconfig
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/usr/local/lib/python3/dist-packages \
    FLEXRIC_SDK_PATH=/usr/local/lib/python3/dist-packages/xapp_sdk

FROM runtime AS ric
STOPSIGNAL SIGINT
ENTRYPOINT ["stdbuf", "-oL", "-eL", "/usr/local/bin/flexric/ric/nearRT-RIC"]
CMD ["-c", "/usr/local/etc/flexric/ric.conf"]

FROM runtime AS emulator
STOPSIGNAL SIGINT
ENTRYPOINT ["stdbuf", "-oL", "-eL", "/usr/local/bin/flexric/e2agent/emu_agent_gnb"]
CMD ["-c", "/usr/local/etc/flexric/e2agent.conf"]

FROM runtime AS xapp
COPY test/xapp/ /opt/oai-pi/test/xapp/
WORKDIR /opt/oai-pi/test/xapp
ENTRYPOINT ["python3"]
CMD ["xapp_nodes.py", "-c", "/usr/local/etc/flexric/xapp.conf"]
