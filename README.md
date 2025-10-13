# OAI-5GC Raspberry Pi Port

This project focuses on **porting OAI-5GC (OpenAirInterface 5G Core)** to Raspberry Pi devices. It enables lightweight and portable 5G core testing environments on ARM-based hardware, particularly **Raspberry Pi 4**.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Deployment and Running](#deployment-and-running)
- [Testing and Verification](#testing-and-verification)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)
- [Contact](#contact)

---

## Overview

The main goal of this project is to adapt **Open5GS** for Raspberry Pi, providing:

- Containerized Open5GS images for ARM architecture.
- Deployment and execution on Raspberry Pi 4.
- Basic 5G core functionality for experimentation and learning.

Currently, the project has successfully:

- Built and tested Open5GS container images for ARM.
- Verified containerized Open5GS running on Raspberry Pi 4.

---

## Features

- ARM-compatible Open5GS container images
- Supports Raspberry Pi 4 and higher
- Docker and Docker Compose deployment
- Suitable for small-scale 5G core testing
- Easy-to-use scripts for building and running containers

---

## Requirements

- Raspberry Pi 4 (4GB or 8GB recommended)
- Docker >= 20.x
- Docker Compose >= 1.29.x
- Linux-based OS (Raspberry Pi OS, Ubuntu Server, etc.)
- Network connectivity for containerized 5G core

---

## Installation

1. **Clone the repository**
```bash
git clone <repository-url>
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

3. **(Optional) Add your user to Docker group**
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

## Testing and Verification

- Check logs of key Open5GS components:
```bash
docker logs oai-mme
docker logs oai-sgw
docker logs oai-pgw
```

- Test connectivity with UE simulators or test devices.

- Confirm that Open5GS functions as expected (attach/detach, session creation, etc.)

---

## Contributing

Contributions are welcome! You can contribute by:

1. **Code Contributions**
   - Fork the repository
   - Create a new branch:
     ```bash
     git checkout -b feature/my-feature
     ```
   - Make your changes and commit:
     ```bash
     git commit -m "Add new feature"
     ```
   - Push your branch and open a Merge Request (MR):
     ```bash
     git push origin feature/my-feature
     ```

2. **Documentation**
   - Improve instructions, add examples, or clarify troubleshooting steps.

3. **Testing**
   - Test containers on Raspberry Pi and report issues or improvements.

---

## License

Specify your license here (e.g., MIT License)

---

## Acknowledgements

- [OpenAirInterface](https://www.openairinterface.org/)
- [Open5GS](https://open5gs.org/)

---

## Contact

For questions or support, contact limx59@163.com via GitLab or email.
