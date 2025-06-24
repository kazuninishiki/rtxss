# RTXSS - RTX System Stats

> Real-time NVIDIA GPU monitoring tool with web interface

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)

## 🚀 Features

- **Real-time GPU Monitoring** - Temperature, power, utilization, memory usage
- **Web Interface** - Responsive design accessible from any device on your network
- **System Tray Integration** - Runs quietly in the background
- **Power Controls** - Adjust GPU power limits (400W-600W)
- **Process Monitoring** - See which applications are using your GPU
- **Performance Charts** - Historical temperature and power consumption graphs
- **PCIe Information** - Current vs maximum generation, lanes, and transfer rates
- **Auto-start Support** - Automatically start with Windows
- **Standalone Executable** - Single .exe file with no dependencies

## 📸 Screenshots

### Main Interface
![Interface image](https://github.com/kazuninishiki/rtxss/blob/main/interface.png?raw=true)
The web interface displays comprehensive GPU metrics including temperature, power consumption, memory usage, and PCIe information.

### System Tray
Convenient system tray integration with server controls and browser launching.

## 🔧 Requirements

### For Running (Compiled Version)
- Windows 10/11
- NVIDIA GPU with recent drivers
- `nvidia-smi` available in PATH

### For Development
- Python 3.8+
- NVIDIA GPU with drivers supporting `nvidia-smi`
- Required Python packages (see `requirements.txt`)

## 📦 Installation

### Option 1: Download Compiled Executable (Recommended)
1. Download `rtxss.exe` from the [latest release](https://github.com/USERNAME/rtxss/releases)
2. Place it in any folder
3. Run `rtxss.exe`
4. Access the web interface at `http://localhost:9876`

### Option 2: Run from Source
```bash
# Clone the repository
git clone https://github.com/USERNAME/rtxss.git
cd rtxss

# Install dependencies
pip install -r requirements.txt

# Run the application
python rtxss.py
```

### Option 3: Compile Your Own Executable
```bash
# Clone and navigate to directory
git clone https://github.com/USERNAME/rtxss.git
cd rtxss

# Run the compiler script
python compile_rtxss.py

# Find your executable in dist/rtxss.exe
```

## 🖥️ Usage

### Starting the Application
1. **Run `rtxss.exe`** - A green GPU icon appears in your system tray
2. **Auto-start enabled** - The web server starts automatically
3. **Access web interface** - Open `http://localhost:9876` in any browser

### System Tray Menu
- **Start Server** - Start the web server
- **Stop Server** - Stop the web server  
- **Open Browser** - Launch default browser to the interface
- **Toggle Auto-Start** - Enable/disable Windows startup
- **Quit** - Exit the application

### Web Interface Features
- **GPU Table** - Real-time metrics for your graphics card
- **Power Control Panel** - Adjust power limits and view current status
- **Performance Charts** - Temperature and power history graphs
- **Process Monitor** - Applications currently using GPU resources

### Power Management
Use the power control buttons to set GPU power limits:
- **400W** - Power saving mode
- **450W** - Balanced performance
- **500W** - Default performance
- **550W** - High performance  
- **600W** - Maximum performance

## 🌐 Network Access

The web interface is accessible from other devices on your network:
- **Local access**: `http://localhost:9876`
- **Network access**: `http://YOUR_IP_ADDRESS:9876`

Find your IP address with `ipconfig` in Command Prompt.

## 📊 Monitoring Features

### GPU Metrics
- **Name** - GPU model (e.g., RTX 5090)
- **Temperature** - Current GPU temperature
- **Fan Speed** - Current fan percentage
- **Power** - Real-time power consumption
- **GPU Utilization** - Graphics processing load
- **Memory Utilization** - VRAM usage percentage
- **Memory Usage** - VRAM used in MB
- **PCIe Generation** - Current/Max PCIe generation
- **PCIe Lanes** - Current/Max lane count
- **Transfer Rate** - Current/Max GT/s
- **Driver Version** - NVIDIA driver version
- **CUDA Version** - CUDA toolkit version

### Process Information
- **Process Name** - Application using GPU
- **RAM Usage** - System memory percentage

## ⚙️ Configuration

### Update Interval
Adjust the refresh rate in the web interface footer:
- **Range**: 100ms to 10000ms
- **Default**: 1000ms (1 second)
- **Input method**: Type value and press Enter or click Set

### Log Files
The application creates detailed logs in the same directory:
- **File**: `rtxss.log`
- **Size**: 5MB max with 3 backup files
- **Content**: Startup info, errors, and debug information

## 🔧 Troubleshooting

### Common Issues

**Web interface not loading:**
- Check if port 9876 is blocked by firewall
- Verify RTXSS is running (check system tray)
- Try `http://127.0.0.1:9876` instead of localhost

**GPU data not showing:**
- Ensure NVIDIA drivers are installed
- Verify `nvidia-smi` works in Command Prompt
- Check `rtxss.log` for specific error messages

**System tray icon missing:**
- Check Windows notification area settings
- Look for hidden icons in system tray overflow

**Power limit changes not working:**
- Run as Administrator (some GPUs require elevated privileges)
- Check if your GPU supports power limit modification
- Verify in `rtxss.log` for permission errors

### Getting Help
1. **Check the log file** (`rtxss.log`) for error details
2. **Verify nvidia-smi works**: Open Command Prompt and run `nvidia-smi`
3. **Test basic functionality**: Try accessing `http://localhost:9876`
4. **Create an issue** on GitHub with log file contents

## 🔒 Security Notes

- The web server runs locally and accepts connections from your network
- No authentication is required for the web interface
- Consider firewall rules if exposing to untrusted networks
- GPU power changes require appropriate system permissions

## 🤝 Contributing

Contributions are welcome! Please feel free to submit pull requests or create issues for bugs and feature requests.

### Development Setup
```bash
git clone https://github.com/USERNAME/rtxss.git
cd rtxss
pip install -r requirements.txt
python rtxss.py
```

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- **Flask & Flask-SocketIO** - Web framework and real-time communication
- **Chart.js** - Beautiful performance charts
- **pystray** - System tray integration
- **psutil** - System and process utilities

## 📋 Version History

### v1.0.0 - Initial Release
- Real-time GPU monitoring
- Web interface with responsive design
- System tray integration
- Power control functionality
- Process monitoring
- Auto-start support
- Standalone executable compilation

---

**Built for NVIDIA GPU enthusiasts who want comprehensive, real-time monitoring with modern web interface.**
