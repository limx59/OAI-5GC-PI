# Experimental OCUDU Split 8 gNB for Raspberry Pi 5.
# Source remains unchanged; build uses a Docker copy.
FROM ubuntu:24.04 AS builder

ARG BUILD_JOBS=2
ARG MCPU=cortex-a76+crypto
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build pkg-config git ca-certificates \
    python3 libfftw3-dev libmbedtls-dev libsctp-dev libyaml-cpp-dev \
    libzmq3-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY ocudu/ /src/ocudu/

RUN pkg-config --exists libzmq \
    && cmake -S /src/ocudu -B /build/ocudu -G Ninja \
       -DCMAKE_BUILD_TYPE=Release \
       -DMCPU="${MCPU}" \
       -DMARCH=armv8.2-a \
       -DBUILD_TESTING=OFF \
       -DENABLE_ZEROMQ=ON \
       -DENABLE_EXPORT=ON \
       -DENABLE_FFTW=ON \
       -DENABLE_UHD=OFF \
       -DENABLE_SIDEKIQ=OFF \
       -DENABLE_DIFI=OFF \
       -DENABLE_DPDK=OFF \
       -DENABLE_CUDA=OFF \
       -DENABLE_MKL=OFF \
       -DENABLE_FFTZ=OFF \
       -DENABLE_ARMPL=OFF \
       -DENABLE_BACKWARD=OFF \
       -DENABLE_PLUGINS=OFF \
    && cmake --build /build/ocudu \
       --target gnb_split_8 --parallel "${BUILD_JOBS}"

RUN test -s /build/ocudu/apps/gnb_split_8/gnb \
    && mkdir -p /stage/opt/ocudu/bin \
    && install -m 755 /build/ocudu/apps/gnb_split_8/gnb \
       /stage/opt/ocudu/bin/gnb

FROM ubuntu:24.04 AS gnb

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini libfftw3-single3 libmbedcrypto7t64 libsctp1 libyaml-cpp0.8 \
    libzmq5 libssl3t64 libstdc++6 libgcc-s1 \
    iproute2 iputils-ping procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /stage/opt/ocudu/ /opt/ocudu/
COPY ocudu/LICENSE /opt/ocudu/licenses/LICENSE
COPY ocudu/COPYRIGHTS.txt /opt/ocudu/licenses/COPYRIGHTS.txt
COPY ocudu/LICENSES/ /opt/ocudu/licenses/LICENSES/

LABEL org.opencontainers.image.source="https://gitlab.com/ocudu/ocudu" \
      org.opencontainers.image.revision="440cdbbee077e97e824db285bf227c15c84bd0bb"

WORKDIR /opt/ocudu/bin
RUN set -eu; \
    ldd ./gnb > /tmp/gnb-ldd.txt; \
    cat /tmp/gnb-ldd.txt; \
    if grep -q 'not found' /tmp/gnb-ldd.txt; then exit 1; fi; \
    rm /tmp/gnb-ldd.txt

STOPSIGNAL SIGINT
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/opt/ocudu/bin/gnb"]
CMD ["-c", "/etc/ocudu/gnb.yml"]
