# Runtime CUDA 12.x alinhado com wheels PyTorch comuns (driver NVIDIA no host)
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# Evita interação
ENV DEBIAN_FRONTEND=noninteractive

# Atualiza e instala dependências básicas
RUN apt-get update && apt-get install -y \
    python3.11 python3-pip git wget ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Define Python 3
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# Diretório da app
WORKDIR /app

# Copia requirements
COPY app/requirements.txt .

# Instala dependências Python
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copia app
COPY app/ ./app

# Expõe porta
EXPOSE 1005

# Comando padrão para rodar API
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "1005"]