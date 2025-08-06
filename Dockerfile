# Stage 1: Build the environment with dependencies
FROM python:3.11-slim-bookworm AS builder

# Set environment variables to prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Create a virtual environment
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install Python dependencies into the virtual environment (using a mirror for acceleration)
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# Download only Playwright's Chromium browser; system dependencies will be installed in the next stage
RUN playwright install chromium

# Stage 2: Create the final, lean image
FROM python:3.11-slim-bookworm

# Set the working directory and environment variables
WORKDIR /app
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
# Add a new environment variable to distinguish between Docker and local environments
ENV RUNNING_IN_DOCKER=true
# Tell Playwright where to find the browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

# Copy the virtual environment from the builder stage, so we can use the playwright command
COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

# Install the system-level dependencies required to run the browser
RUN sed -i 's|http://deb.debian.org|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && playwright install-deps chromium \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-downloaded browser from the builder stage
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

# Copy the application code
# The .dockerignore file will handle exclusions
COPY . .

# Declare the port the service will run on
EXPOSE 8000

# The command to execute when the container starts
CMD ["python", "web_server.py"]
