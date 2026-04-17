FROM python:3.11

WORKDIR /app

RUN pip install --upgrade pip setuptools wheel

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY receptor.py .

CMD ["python", "receptor.py"]