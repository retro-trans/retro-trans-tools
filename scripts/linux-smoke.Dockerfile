FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends xvfb xauth ca-certificates fonts-dejavu-core libicu74 && rm -rf /var/lib/apt/lists/*
ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1
CMD ["sh", "-ec", "! command -v python3; ! command -v dotnet; ! command -v chdman; ! command -v dolphin-tool; work=$(mktemp -d); export HOME=$work RETRO_TRANS_DATA_DIR=$work/data; tar -xzf /packages/Retro-Trans-Linux-*.tar.gz -C \"$work\"; cd /tmp; xvfb-run -a \"$work/Retro-Trans/Retro-Trans\" --health-check /results/CLEAN-LINUX-HEALTH.json"]
