FROM python:3.8-slim
RUN mkdir -p /project
RUN apt-get update && apt-get install -y tesseract-ocr && apt-get install -y imagemagick && apt-get clean
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY results_aioserver.py ./
CMD ["python", "results_aioserver.py"]