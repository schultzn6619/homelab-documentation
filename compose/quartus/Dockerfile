FROM raetro/quartus:13.0sp1 AS quartus

FROM lscr.io/linuxserver/webtop:ubuntu-xfce
COPY --from=quartus /opt/intelFPGA /opt/intelFPGA

RUN dpkg --add-architecture i386 && apt-get update && \
    apt-get install -y --no-install-recommends \
      libc6:i386 libncurses6:i386 libxtst6:i386 libxft2:i386 \
      libsm6:i386 libxrender1:i386 libxi6:i386 libfreetype6:i386 \
      libglib2.0-0t64:i386 libx11-6:i386 libxext6:i386 \
      libsm6 libxrender1 libxi6 libfreetype6 locales && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/libpng12.deb \
      http://archive.ubuntu.com/ubuntu/pool/main/libp/libpng/libpng12-0_1.2.54-1ubuntu1_amd64.deb && \
    mkdir /tmp/x && dpkg-deb -x /tmp/libpng12.deb /tmp/x && \
    cp -L /tmp/x/lib/x86_64-linux-gnu/libpng12.so.0 /opt/intelFPGA/quartus/linux64/ && \
    rm -rf /tmp/x /tmp/libpng12.deb

ENV PATH="/opt/intelFPGA/quartus/bin:${PATH}"
