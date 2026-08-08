# 1. Usamos una imagen oficial de Python ligera
FROM python:3.11-slim

# 2. Configuración para que Python no guarde archivos de caché (.pyc) y muestre logs al instante
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. Creamos y nos situamos en la carpeta de trabajo dentro del contenedor
WORKDIR /app

# 4. Copiamos e instalamos primero las librerías para aprovechar la caché de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copiamos el resto de los archivos del proyecto (main.py, init_db.py, templates, etc.)
COPY . .

# 6. Exponemos el puerto 8000 donde escuchará FastAPI
EXPOSE 8000

# 7. Comando para arrancar el servidor web
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]