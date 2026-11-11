FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends xvfb xauth ca-certificates fonts-dejavu-core fontconfig libicu74 && rm -rf /var/lib/apt/lists/*
ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1
CMD ["sh", "-ec", "test \"$(id -u)\" -ne 0; for tool in python3 dotnet chdman dolphin-tool; do if command -v \"$tool\"; then exit 1; fi; done; work=$(mktemp -d); export HOME=$work RETRO_TRANS_DATA_DIR=$work/data; tar -xzf /packages/Retro-Trans-Linux-*.tar.gz -C \"$work\"; cd /tmp; xvfb-run -a \"$work/Retro-Trans/Retro-Trans\" --health-check /results/CLEAN-LINUX-HEALTH.json"]
