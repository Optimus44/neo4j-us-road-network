# Start from the official Python 3.11 slim image
# "slim" means minimal OS — smaller download, less disk space
FROM python:3.11-slim

# Set the working directory inside the container
# All subsequent commands run from here
WORKDIR /app

# Copy requirements first — Docker caches this layer
# If requirements don't change, this layer is reused on rebuild
COPY requirements.txt .

# Install Python dependencies
# --no-cache-dir reduces image size by not storing pip's download cache
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
# This is done AFTER installing requirements so that code changes
# don't invalidate the requirements cache layer
COPY . .

# The command that runs when the container starts
CMD ["python", "ingest.py"]