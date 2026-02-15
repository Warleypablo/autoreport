# Use imagem base leve do Python
FROM python:3.10-slim

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Copia os arquivos de dependências primeiro para melhor cache
COPY requirements.txt .

# Instala as dependências do projeto
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o resto do projeto para dentro do container
COPY . .

# Expõe porta da interface web
EXPOSE 5000

# Comando padrão: interface web
# Para CLI: docker run auto-report python report_generator.py
CMD ["python", "app.py"]