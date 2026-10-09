FROM ubuntu:24.04 AS builder

ARG BUILD_JOBS=2
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build pkg-config git ca-certificates \
    autoconf automake libtool bison flex patch ccache \
    python3 python3-dev python3-yaml xxd \
    libreadline-dev libconfig-dev libsctp-dev libssl-dev zlib1g-dev \
    libyaml-cpp-dev libpcre2-dev libcap-dev libzstd-dev \
    flatbuffers-compiler libflatbuffers-dev libnanomsg-dev libzmq3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/mouse07410/asn1c /tmp/asn1c \
    && cd /tmp/asn1c \
    && git checkout 940dd5fa9f3917913fd487b13dfddfacd0ded06e \
    && autoreconf -iv \
    && CFLAGS="-O2 -fno-strict-aliasing" ./configure --prefix=/opt/asn1c \
    && make -j"${BUILD_JOBS}" \
    && make install \
    && rm -rf /tmp/asn1c

RUN git clone https://github.com/simd-everywhere/simde-no-tests.git /tmp/simde \
    && cd /tmp/simde \
    && git checkout 1c68d9ad60bf63f3fb527c4ee3b2319d828ffcc6 \
    && cp -r /tmp/simde /usr/include/ \
    && rm -rf /tmp/simde

COPY oai/ /src/oai/
WORKDIR /src/oai

RUN cmake -S /src/oai -B /build/oai -G Ninja \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DE2_AGENT=ON \
    -DE2AP_VERSION=E2AP_V2 \
    -DKPM_VERSION=KPM_V3_00 \
    -DOAI_USRP=OFF \
    && cmake --build /build/oai \
       --target nr-softmodem rfsimulator coding dfts params_libconfig params_yaml kpm_sm mac_sm rlc_sm pdcp_sm \
       --parallel "${BUILD_JOBS}"

RUN mkdir -p /stage/opt/oai-gnb/bin/e2-sm-plugins-kpm \
             /stage/opt/oai-gnb/lib \
    && install -m 755 /build/oai/nr-softmodem /stage/opt/oai-gnb/bin/ \
    && find /build/oai -maxdepth 1 -name '*.so' -type f \
       -exec cp '{}' /stage/opt/oai-gnb/lib/ ';' \
    && install -m 755 \
       /build/oai/openair2/E2AP/flexric/src/sm/kpm_sm/kpm_sm_v03.00/libkpm_sm.so \
       /stage/opt/oai-gnb/bin/e2-sm-plugins-kpm/

# Keep the configured plugin directory while adding custom statistics models.
RUN set -eu; \
    for model in mac rlc pdcp; do \
      install -m 755 \
        "/build/oai/openair2/E2AP/flexric/src/sm/${model}_sm/lib${model}_sm.so" \
        /stage/opt/oai-gnb/bin/e2-sm-plugins-kpm/; \
    done

FROM ubuntu:24.04 AS gnb

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini python3 libsctp1 libconfig9 libyaml-cpp0.8 \
    libssl3t64 libreadline8t64 zlib1g libcap2 libzstd1 \
    libnanomsg5 libzmq5 libstdc++6 libgcc-s1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /stage/opt/oai-gnb/ /opt/oai-gnb/
ENV LD_LIBRARY_PATH=/opt/oai-gnb/lib
WORKDIR /opt/oai-gnb/bin

RUN set -eu; \
    for library in ./nr-softmodem /opt/oai-gnb/lib/*.so ./e2-sm-plugins-kpm/*.so; do \
      ldd "$library" > /tmp/ldd-check.txt; \
      cat /tmp/ldd-check.txt; \
      if grep -q 'not found' /tmp/ldd-check.txt; then exit 1; fi; \
    done; \
    rm /tmp/ldd-check.txt

STOPSIGNAL SIGINT
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "stdbuf", "-oL", "-eL", "/opt/oai-gnb/bin/nr-softmodem"]
CMD ["-O", "/etc/oai/gnb.conf", "--rfsim"]

FROM builder AS nrue-builder

ARG BUILD_JOBS=2
RUN cmake --build /build/oai \
    --target nr-uesoftmodem rfsimulator coding dfts params_libconfig params_yaml \
    --parallel "${BUILD_JOBS}"

RUN mkdir -p /stage/opt/oai-nr-ue/bin /stage/opt/oai-nr-ue/lib \
    && install -m 755 /build/oai/nr-uesoftmodem /stage/opt/oai-nr-ue/bin/ \
    && find /build/oai -maxdepth 1 -name '*.so' -type f \
       -exec cp '{}' /stage/opt/oai-nr-ue/lib/ ';'

FROM ubuntu:24.04 AS nrue

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini python3 libsctp1 libconfig9 libyaml-cpp0.8 \
    libssl3t64 libreadline8t64 zlib1g libcap2 libzstd1 \
    libnanomsg5 libzmq5 libstdc++6 libgcc-s1 \
    iproute2 iputils-ping iperf3 procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=nrue-builder /stage/opt/oai-nr-ue/ /opt/oai-nr-ue/
ENV LD_LIBRARY_PATH=/opt/oai-nr-ue/lib
WORKDIR /opt/oai-nr-ue/bin

RUN set -eu; \
    for library in ./nr-uesoftmodem /opt/oai-nr-ue/lib/*.so; do \
      ldd "$library" > /tmp/ldd-check.txt; \
      cat /tmp/ldd-check.txt; \
      if grep -q 'not found' /tmp/ldd-check.txt; then exit 1; fi; \
    done; \
    rm /tmp/ldd-check.txt

STOPSIGNAL SIGINT
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "stdbuf", "-oL", "-eL", "/opt/oai-nr-ue/bin/nr-uesoftmodem"]
CMD ["-O", "/etc/oai/ue.conf", "--rfsim"]
