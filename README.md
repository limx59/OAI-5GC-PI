# OAI-5GC Raspberry Pi Port

This project focuses on **porting OAI-5GC (OpenAirInterface 5G Core)** to Raspberry Pi devices.  
It enables lightweight and portable 5G core testing environments on ARM-based hardware, particularly **Raspberry Pi 4 and Raspberry Pi 5**.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Deployment and Running](#deployment-and-running)
- [Docker Images](#docker-images)
- [Testing and Verification](#testing-and-verification)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)
- [Contact](#contact)

---

## Overview

The main goal of this project is to adapt **Open5GS** and **OAI 5G Core** for Raspberry Pi, providing:

- Containerized 5G Core images for **ARM architecture**
- Deployment and execution on **Raspberry Pi 4 / 5**
- Basic 5G core functionality for experimentation and learning

Currently, the project has successfully:

- Built and tested **Open5GS container images** for ARM
- Verified containerized **Open5GS** running on **Raspberry Pi 4 and Raspberry Pi 5**

---

## Features

- ✅ ARM-compatible **Open5GS** and **OAI-5GC** container images  
- ✅ Supports **Raspberry Pi 4 / 5**  
- ✅ Deployable via **Docker** and **Docker Compose**  
- ✅ Lightweight 5G core environment for testing and education  
- ✅ Includes example configurations and startup scripts  

---

## Requirements

- Raspberry Pi 4 (4GB or 8GB recommended) or Raspberry Pi 5  
- Docker ≥ 20.x  
- Docker Compose ≥ 1.29.x  
- Linux-based OS (Raspberry Pi OS, Ubuntu Server, etc.)  
- Network connectivity for 5G core containers  

---

## Installation

1. **Clone the repository**
```bash
git clone https://gitlab.com/limx59/oai-5gc-pi.git
cd oai-5gc-pi
```

2. **Install Docker and Docker Compose**
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt install -y docker-compose
```

3. **(Optional) Add your user to the Docker group**
```bash
sudo usermod -aG docker $USER
newgrp docker
```

---

## Deployment and Running

1. **Build or pull container images**
```bash
docker-compose build      # Build locally
docker-compose pull       # Pull pre-built images
```

2. **Start the containers**
```bash
docker-compose up -d
```

3. **Check running containers**
```bash
docker ps
```

4. **Stop the containers**
```bash
docker-compose down
```

---

## Docker Images

Pre-built **Open5GS ARM Docker images** are available on Docker Hub:  

👉 **[https://hub.docker.com/u/limx59](https://hub.docker.com/u/limx59)**

These images have been **tested and verified to run properly on Raspberry Pi 5**.  
You can directly pull and use them without manual build steps:

```bash
docker pull limx59/open5gs-amf:latest
docker pull limx59/open5gs-smf:latest
docker pull limx59/open5gs-upf:latest
docker pull limx59/open5gs-hss:latest
docker pull limx59/open5gs-pcrf:latest
docker pull limx59/open5gs-webui:latest
```

### ReDroid Android UI (ARM64)

A tested mirror of the official ReDroid Android 12 ARM64 image is available
on [Docker Hub](https://hub.docker.com/r/limx59/redroid):

```bash
sudo docker pull --platform linux/arm64 limx59/redroid:12.0.0-arm64
```

ReDroid provides the Android UI; UERANSIM performs simulated 5G registration.
Android browser traffic can use the UE PDU session through Tinyproxy.

- [Installation and UE proxy configuration](third_party/redroid/README.md)
- [ARM64 source build instructions](third_party/redroid/src/README.md)

The published image is an upstream mirror. The source build procedure has
not yet been validated by a complete build.

To start all services using Docker Compose:
```bash
docker-compose -f docker-compose.open5gs.yaml up -d
```

---

## Testing and Verification

Open5GS core validation: [AUSF stale NF reference and real UE tests](test/open5gs/README.md).

- Check logs of key Open5GS components:
```bash
docker logs open5gs-amf
docker logs open5gs-smf
docker logs open5gs-upf
```

- Test with UE simulators or test devices.
- Confirm Open5GS attach/detach and session creation procedures.
- Validate web interface (WebUI) is accessible for subscriber management.

---

## Contributing

Contributions are welcome! You can contribute by:

### 1. Code Contributions
```bash
# Fork the repository
git checkout -b feature/my-feature
# Commit changes
git commit -m "Add new feature"
# Push and open Merge Request
git push origin feature/my-feature
```

### 2. Documentation
- Improve setup instructions or add Raspberry Pi optimization tips.

### 3. Testing
- Test container deployment on different Raspberry Pi models and report feedback.

---

## License

Specify your license here (e.g., **MIT License**)

This project references:
- [Open5GS (GNU AGPL v3.0)](https://open5gs.org/)
- [OpenAirInterface (OAI Public License 1.1)](https://www.openairinterface.org/)

---

## Acknowledgements

- [OpenAirInterface](https://www.openairinterface.org/)
- [Open5GS](https://open5gs.org/)
- [Docker Hub Repository - limx59](https://hub.docker.com/u/limx59)

---

## Contact

For questions or support, contact:  
📧 **limx59@163.com**
